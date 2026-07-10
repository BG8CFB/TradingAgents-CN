"""统一读取层 — 从 MongoDB 读标准数据 + 新鲜度判定 + 异步刷新通知。"""

import logging
import math
import re
import threading
from datetime import datetime, date, timezone
from typing import Any, Dict, Optional, Tuple

from app.data.schema.base.enums import FreshnessState

logger = logging.getLogger(__name__)


def _strip_nan(value: Any) -> Any:
    """递归剔除 NaN/Inf，替换为 None，确保返回值可被 JSON 序列化。

    历史脏数据（如 basic_info.industry 为 NaN）会在 BSON→Python 反序列化后
    变成 float('nan')，FastAPI 默认 JSON 编码器会抛出
    "Out of range float values are not JSON compliant"。这里作为读取层的
    最后防线，统一兜底。
    """
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return None
        return value
    if isinstance(value, dict):
        return {k: _strip_nan(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_strip_nan(v) for v in value]
    if isinstance(value, tuple):
        return tuple(_strip_nan(v) for v in value)
    return value


def _norm_date(d: str) -> str:
    """归一化日期格式：YYYYMMDD → YYYY-MM-DD（已是 YYYY-MM-DD 则原样返回）。"""
    if not d:
        return d
    if "-" in d:
        return d
    if re.match(r"^\d{8}$", d):
        return f"{d[:4]}-{d[4:6]}-{d[6:]}"
    return d


def _to_ymd(d) -> str:
    """归一化日期为 YYYYMMDD（兼容 YYYY-MM-DD / YYYYMMDD / date/datetime）。"""
    if d is None:
        return ""
    if isinstance(d, (datetime, date)):
        return d.strftime("%Y%m%d")
    s = str(d).strip()
    if re.match(r"^\d{4}-\d{2}-\d{2}", s):
        return s.replace("-", "")[:8]
    return s.replace("-", "")[:8]


class Reader:
    """统一读取层。消费方通过 Reader 获取标准数据，不直接访问 MongoDB。"""

    def __init__(self):
        self._repo_cache: Dict[str, Any] = {}
        self._refresh_queue = None
        self._repo_lock = threading.Lock()

    def _get_repo(self, domain: str):
        """按域获取对应仓储。"""
        if domain in self._repo_cache:
            return self._repo_cache[domain]

        with self._repo_lock:
            # 双重检查
            if domain in self._repo_cache:
                return self._repo_cache[domain]

            from app.data.storage.mongo.repositories import (
                BasicInfoRepo, DailyQuotesRepo, DailyIndicatorsRepo,
                AdjFactorsRepo, CorporateActionsRepo, FinancialDataRepo,
                MarketQuotesRepo, NewsRepo, TradeCalendarRepo,
                IntradayQuotesRepo, MoneyFlowRepo, MarginTradingRepo,
                DragonTigerRepo, BlockTradeRepo,
                ConnectStatusRepo, SouthboundHoldingRepo, PrePostMarketRepo,
            )

            repo_map = {
                "basic_info": BasicInfoRepo,
                "trade_calendar": TradeCalendarRepo,
                "daily_quotes": DailyQuotesRepo,
                "daily_indicators": DailyIndicatorsRepo,
                "adj_factors": AdjFactorsRepo,
                "corporate_actions": CorporateActionsRepo,
                "financial_data": FinancialDataRepo,
                "market_quotes": MarketQuotesRepo,
                "news": NewsRepo,
                "intraday_quotes": IntradayQuotesRepo,
                "money_flow": MoneyFlowRepo,
                "margin_trading": MarginTradingRepo,
                "dragon_tiger": DragonTigerRepo,
                "block_trade": BlockTradeRepo,
                "connect_status": ConnectStatusRepo,
                "southbound_holding": SouthboundHoldingRepo,
                "pre_post_market": PrePostMarketRepo,
            }

            repo_cls = repo_map.get(domain)
            if repo_cls:
                repo = repo_cls()
            else:
                # 新域使用通用 Repository
                from app.data.storage.mongo.repositories.generic_repo import GenericRepo
                repo = GenericRepo(domain)
            self._repo_cache[domain] = repo
            return repo

    async def get_data(
        self, market: str, domain: str, symbol: Optional[str] = None,
        start_date: Optional[str] = None, end_date: Optional[str] = None,
        filters: Optional[Dict] = None,
    ) -> Tuple[Optional[Any], str]:
        """读取数据并返回 (data, freshness_state)。

        Args:
            market: 市场
            domain: 数据域
            symbol: 股票代码（可选）
            start_date: 起始日期
            end_date: 结束日期
            filters: 额外过滤条件
        """
        repo = self._get_repo(domain)
        if not repo:
            return None, FreshnessState.UNKNOWN

        filters = filters or {}
        data = None

        if domain == "basic_info":
            if symbol:
                data = await repo.get_by_symbol(symbol, market)
            else:
                limit = filters.get("limit", 0)
                data = await repo.get_all(market, limit=limit)

        elif domain == "trade_calendar":
            exchange = filters.get("exchange",
                                   "SSE" if market == "CN" else "HKEX" if market == "HK" else "NYSE")
            data = await repo.get_range(exchange, market,
                                        start_date or "1970-01-01", end_date or "2099-12-31")

        elif domain in ("daily_quotes", "daily_indicators", "adj_factors", "corporate_actions"):
            if symbol:
                period_filter = filters.get("period") if filters else None
                extra_kwargs = {}
                if period_filter and domain == "daily_quotes":
                    extra_kwargs["period"] = period_filter
                data = await repo.get_by_symbol_and_range(
                    symbol, market,
                    start_date or "1970-01-01", end_date or "2099-12-31",
                    **extra_kwargs,
                )

        elif domain == "financial_data":
            if symbol:
                statement_type = filters.get("statement_type")
                data = await repo.get_by_symbol(symbol, market, statement_type=statement_type)

        elif domain == "market_quotes":
            if symbol:
                data = await repo.get_by_symbol(symbol, market)
            else:
                limit = filters.get("limit", 100)
                data = await repo.get_all(market, limit=limit)

        elif domain == "news":
            if symbol:
                limit = filters.get("limit", 20)
                data = await repo.get_by_symbol(symbol, market, limit=limit)
                # 补充市场级新闻（symbol="" 的全市场新闻）
                market_news = await repo.get_by_symbol("", market, limit=limit)
                if market_news:
                    seen = {d.get("title") for d in (data or [])}
                    for item in market_news:
                        if item.get("title") not in seen:
                            data.append(item)
                            seen.add(item.get("title"))

                    def _sort_key(x):
                        pt = x.get("publish_time", "")
                        if isinstance(pt, str):
                            return pt
                        return str(pt) if pt else ""
                    data.sort(key=_sort_key, reverse=True)
                    data = data[:limit]
            else:
                limit = filters.get("limit", 100)
                data = await repo.get_all(market, limit=limit)

        elif domain == "intraday_quotes":
            if symbol:
                freq = filters.get("freq")
                data = await repo.get_by_symbol_and_range(
                    symbol, market,
                    start_date or "1970-01-01 00:00:00",
                    end_date or "2099-12-31 23:59:59",
                    freq=freq,
                )

        elif domain == "money_flow":
            sd = _norm_date(start_date) if start_date else "1970-01-01"
            ed = _norm_date(end_date) if end_date else "2099-12-31"
            if symbol and symbol not in ("__all__", "market"):
                data = await repo.get_by_symbol_and_range(symbol, market, sd, ed)
            else:
                limit = filters.get("limit", 1000) if filters else 1000
                data = await repo.get_by_date_range(market, sd, ed, limit=limit)

        elif domain == "margin_trading":
            sd = _norm_date(start_date) if start_date else "1970-01-01"
            ed = _norm_date(end_date) if end_date else "2099-12-31"
            if symbol and symbol not in ("__all__", "market"):
                data = await repo.get_by_symbol_and_range(symbol, market, sd, ed)
            else:
                limit = filters.get("limit", 1000) if filters else 1000
                data = await repo.get_by_date_range(market, sd, ed, limit=limit)

        elif domain == "dragon_tiger":
            if symbol:
                limit = filters.get("limit", 50)
                data = await repo.get_by_symbol(symbol, market, limit=limit)
            elif start_date:
                limit = filters.get("limit", 100)
                data = await repo.get_by_date(start_date, market, limit=limit)

        elif domain == "block_trade":
            if symbol:
                limit = filters.get("limit", 50)
                data = await repo.get_by_symbol(symbol, market, limit=limit)
            else:
                limit = filters.get("limit", 100)
                data = await repo.get_by_date_range(
                    market,
                    start_date or "1970-01-01", end_date or "2099-12-31",
                    limit=limit,
                )

        elif domain == "connect_status":
            limit = filters.get("limit", 100)
            data = await repo.get_by_date_range(
                market,
                start_date or "1970-01-01", end_date or "2099-12-31",
                limit=limit,
            )

        elif domain == "southbound_holding":
            if symbol:
                data = await repo.get_by_symbol_and_range(
                    symbol, market,
                    start_date or "1970-01-01", end_date or "2099-12-31",
                )

        elif domain == "pre_post_market":
            if symbol:
                session_type = filters.get("session_type")
                data = await repo.get_by_symbol_and_range(
                    symbol, market,
                    start_date or "1970-01-01", end_date or "2099-12-31",
                    session_type=session_type,
                )
            else:
                limit = filters.get("limit", 100)
                data = await repo.get_by_symbol("", market, limit=limit)

        # ── B 类新域（GenericRepo，数据库日期为 YYYYMMDD） ──
        elif domain in (
            "northbound_flow", "northbound_holding", "share_unlock",
            "pledge", "trading_status", "price_limit",
            "index_data", "chip_distribution",
            "forecast", "express", "dividend",
            "sw_daily", "ths_daily", "limit_step", "moneyflow_ind_dc",
        ):
            if symbol and symbol != "__all__":
                data = await repo.get_by_symbol_and_range(
                    symbol, market,
                    start_date or "19700101", end_date or "20991231",
                )
            else:
                limit = filters.get("limit", 1000) if filters else 1000
                data = await repo.get_by_date_range(
                    market,
                    start_date or "19700101", end_date or "20991231",
                    limit=limit,
                )

        elif domain == "announcement":
            sd = _to_ymd(start_date) if start_date else "19700101"
            ed = _to_ymd(end_date) if end_date else "20991231"
            if symbol and symbol not in ("__all__", "market"):
                data = await repo.get_by_symbol_and_range(symbol, market, sd, ed)
            else:
                limit = filters.get("limit", 1000) if filters else 1000
                data = await repo.get_by_date_range(market, sd, ed, limit=limit)

        if not data:
            return None, FreshnessState.UNKNOWN

        # 新鲜度判定
        freshness = await self.check_freshness(market, symbol or "", domain, data)

        # 异步通知刷新（stale 时且有 symbol）
        if freshness == FreshnessState.STALE and symbol:
            await self.notify_refresh_async(market, symbol, domain)

        return _strip_nan(data), freshness

    async def check_freshness(
        self, market: str, symbol: str, domain: str, data: Any = None
    ) -> str:
        """检查数据新鲜度。"""
        from app.data.config import load_yaml

        rules = load_yaml("freshness_rules.yaml")
        market_rules = rules.get(market, {})
        domain_rule = market_rules.get(domain)

        if not domain_rule:
            return FreshnessState.UNKNOWN

        # 获取最新更新时间：
        # 注意：daily_quotes 等仓储返回的列表可能是 trade_date 升序排列，
        # 因此 data[0] 是最早记录而非最新记录。必须取 max(updated_at) 才正确。
        updated_at = None
        if isinstance(data, dict):
            updated_at = data.get("updated_at")
        elif isinstance(data, list) and data:
            # 从所有记录中取 updated_at 最大值（兼容仓储升序/降序排列）
            candidates = [
                d.get("updated_at")
                for d in data
                if isinstance(d, dict) and d.get("updated_at")
            ]
            if candidates:
                updated_at = max(candidates)

        if not updated_at:
            return FreshnessState.UNKNOWN

        try:
            # Python 3.10 及更早版本的 datetime.fromisoformat 不支持 "Z" 后缀，
            # 需要先归一化；3.11+ 原生支持，这里统一兼容两种形式。
            iso_str = updated_at.replace("Z", "+00:00") if updated_at.endswith("Z") else updated_at
            updated = datetime.fromisoformat(iso_str)
            if updated.tzinfo is None:
                updated = updated.replace(tzinfo=timezone.utc)
            now = datetime.now(timezone.utc)

            rule_type = domain_rule.get("rule_type", "time_window")

            if rule_type == "time_window":
                threshold_hours = domain_rule.get("threshold_hours")
                threshold_minutes = domain_rule.get("threshold_minutes")
                if threshold_hours:
                    threshold_sec = threshold_hours * 3600
                elif threshold_minutes:
                    threshold_sec = threshold_minutes * 60
                else:
                    return FreshnessState.UNKNOWN

                age_seconds = (now - updated).total_seconds()
                return FreshnessState.FRESH if age_seconds < threshold_sec else FreshnessState.STALE

            elif rule_type == "trading_day_after_close":
                # 简化: 检查数据是否有当天日期
                threshold_minutes = domain_rule.get("threshold_minutes", 60)
                age_minutes = (now - updated).total_seconds() / 60
                return FreshnessState.FRESH if age_minutes < threshold_minutes else FreshnessState.STALE

        except (ValueError, TypeError):
            return FreshnessState.UNKNOWN

        return FreshnessState.UNKNOWN

    async def notify_refresh_async(self, market: str, symbol: str, domain: str) -> None:
        """异步通知刷新服务（非阻塞）。"""
        try:
            if self._refresh_queue is None:
                from app.data.storage.redis.pubsub import RefreshQueue
                self._refresh_queue = RefreshQueue()
            await self._refresh_queue.publish_refresh(market, symbol, domain)
        except Exception as e:
            logger.debug(f"异步刷新通知失败: {e}")
