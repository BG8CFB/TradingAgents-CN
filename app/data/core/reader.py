"""统一读取层 — 从 MongoDB 读标准数据 + 新鲜度判定 + 异步刷新通知。"""

import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

from app.data.schema.base.enums import FreshnessState

logger = logging.getLogger(__name__)


class Reader:
    """统一读取层。消费方通过 Reader 获取标准数据，不直接访问 MongoDB。"""

    def __init__(self):
        self._repo_cache: Dict[str, Any] = {}

    def _get_repo(self, domain: str):
        """按域获取对应仓储。"""
        if domain in self._repo_cache:
            return self._repo_cache[domain]

        from app.data.storage.mongo.repositories import (
            BasicInfoRepo, DailyQuotesRepo, DailyIndicatorsRepo,
            AdjFactorsRepo, CorporateActionsRepo, FinancialDataRepo,
            MarketQuotesRepo, NewsRepo, TradeCalendarRepo,
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
        }

        repo_cls = repo_map.get(domain)
        if repo_cls:
            repo = repo_cls()
            self._repo_cache[domain] = repo
            return repo
        return None

    async def get_data(
        self, market: str, symbol: str, domain: str,
        start_date: Optional[str] = None, end_date: Optional[str] = None,
    ) -> Tuple[Optional[Any], str]:
        """读取数据并返回 (data, freshness_state)。

        Returns:
            Tuple[数据, 新鲜度(fresh/stale/unknown)]
        """
        repo = self._get_repo(domain)
        if not repo:
            return None, FreshnessState.UNKNOWN

        data = None

        if domain == "basic_info":
            data = await repo.get_by_symbol(symbol, market)
        elif domain in ("daily_quotes", "daily_indicators", "adj_factors", "corporate_actions"):
            if start_date and end_date:
                data = await repo.get_by_symbol_and_range(symbol, market, start_date, end_date)
            else:
                data = await repo.get_by_symbol_and_range(symbol, market, "1970-01-01", "2099-12-31")
        elif domain == "financial_data":
            data = await repo.get_by_symbol(symbol, market)
        elif domain == "market_quotes":
            data = await repo.get_by_symbol(symbol, market)
        elif domain == "news":
            data = await repo.get_by_symbol(symbol, market)
        elif domain == "trade_calendar":
            exchange = "SSE" if market == "CN" else "HKEX" if market == "HK" else "NYSE"
            data = await repo.get_range(exchange, market, start_date or "1970-01-01", end_date or "2099-12-31")

        if not data:
            return None, FreshnessState.UNKNOWN

        # 新鲜度判定
        freshness = await self.check_freshness(market, symbol, domain, data)

        # 异步通知刷新（stale 时）
        if freshness == FreshnessState.STALE:
            await self.notify_refresh_async(market, symbol, domain)

        return data, freshness

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

        # 获取最新更新时间
        updated_at = None
        if isinstance(data, dict):
            updated_at = data.get("updated_at")
        elif isinstance(data, list) and data:
            updated_at = data[0].get("updated_at") if isinstance(data[0], dict) else None

        if not updated_at:
            return FreshnessState.UNKNOWN

        try:
            updated = datetime.fromisoformat(updated_at)
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
            from app.data.storage.redis.pubsub import RefreshQueue
            queue = RefreshQueue()
            await queue.publish_refresh(market, symbol, domain)
        except Exception as e:
            logger.debug(f"异步刷新通知失败: {e}")
