"""统一读取层 — 从 MongoDB 读标准数据 + 新鲜度判定 + 异步刷新通知。"""

import logging
import math
import os
import re
import threading
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

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


class Reader:
    """统一读取层。消费方通过 Reader 获取标准数据，不直接访问 MongoDB。"""

    def __init__(self):
        self._repo_cache: Dict[str, Any] = {}
        self._refresh_queue = None
        self._repo_lock = threading.Lock()
        # M8 修复：缓存 freshness_rules.yaml，避免每次 check_freshness 都同步加载。
        self._freshness_rules_cache: Optional[Dict] = None
        self._freshness_rules_mtime: float = 0.0
        self._freshness_rules_lock = threading.Lock()

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
                FactorScoresRepo, ScreeningRecommendationsRepo,
                ScreeningInsightsRepo,
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
                "factor_scores": FactorScoresRepo,
                "screening_recommendations": ScreeningRecommendationsRepo,
                "screening_insights": ScreeningInsightsRepo,
            }

            repo_cls = repo_map.get(domain)
            if repo_cls:
                repo = repo_cls()
                self._repo_cache[domain] = repo
                return repo
            return None

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

        elif domain in ("daily_quotes", "daily_indicators", "adj_factors",
                        "corporate_actions", "factor_scores"):
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
            if symbol:
                data = await repo.get_by_symbol_and_range(
                    symbol, market,
                    start_date or "1970-01-01", end_date or "2099-12-31",
                )

        elif domain == "margin_trading":
            if symbol:
                data = await repo.get_by_symbol_and_range(
                    symbol, market,
                    start_date or "1970-01-01", end_date or "2099-12-31",
                )

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

        if not data:
            return None, FreshnessState.UNKNOWN

        # 新鲜度判定
        freshness = await self.check_freshness(market, symbol or "", domain, data)

        # 异步通知刷新（stale 时且有 symbol）
        if freshness == FreshnessState.STALE and symbol:
            await self.notify_refresh_async(market, symbol, domain)

        return _strip_nan(data), freshness

    # ── Phase 4 新读接口：最新一条 / 批量 / 搜索 ──

    # 各域"最新记录"排序键（与 key_spec 唯一键语义对应：键不含 data_source，
    # 排序也不感知数据源；未列出的域默认按 updated_at 降序兜底）。
    _LATEST_SORT_FIELDS: Dict[str, str] = {
        "trade_calendar": "cal_date",
        "daily_quotes": "trade_date",
        "daily_indicators": "trade_date",
        "adj_factors": "trade_date",
        "corporate_actions": "trade_date",
        "intraday_quotes": "trade_date",
        "money_flow": "trade_date",
        "margin_trading": "trade_date",
        "dragon_tiger": "trade_date",
        "block_trade": "trade_date",
        "southbound_holding": "trade_date",
        "pre_post_market": "trade_date",
        "factor_scores": "trade_date",
        "screening_recommendations": "trade_date",
        "financial_data": "report_period",
        "news": "updated_at",
        "basic_info": "updated_at",
        "market_quotes": "updated_at",
        "connect_status": "updated_at",
    }

    # read_latest_batch 单次 symbols 上限（防止超大 $in 拖垮查询计划）
    MAX_BATCH_SYMBOLS = 500

    @classmethod
    def _latest_sort_field(cls, domain: str) -> str:
        """按域推导"最新一条"的排序键，未知名默认 updated_at。"""
        return cls._LATEST_SORT_FIELDS.get(domain, "updated_at")

    @staticmethod
    def _normalize_projection(projection: Optional[Dict]) -> Dict:
        """投影归一化：默认排除 _id（与既有消费方行为一致）。"""
        if projection is None:
            return {"_id": 0}
        proj = dict(projection)
        if "_id" not in proj:
            proj["_id"] = 0
        return proj

    def _get_coll(self, market: str, domain: str):
        """获取指定域集合（数据层内部直连，消费方不得绕过 Reader 使用）。"""
        from app.data.storage.mongo.client import get_motor_db
        from app.data.storage.mongo.collections import get_collection_name

        db = get_motor_db()
        return db[get_collection_name(domain, market)]

    async def read_latest(
        self, market: str, domain: str, symbol: str,
        projection: Optional[Dict] = None,
    ) -> Optional[Dict]:
        """读取指定股票在某域的最新一条记录。

        排序键按域推导（trade_date/report_period/updated_at 等），
        追加 updated_at 作为次级排序键以稳定同键记录的顺序。
        """
        sort_field = self._latest_sort_field(domain)
        sort_spec = [(sort_field, -1), ("updated_at", -1)]
        coll = self._get_coll(market, domain)
        doc = await coll.find_one(
            {"symbol": symbol},
            self._normalize_projection(projection),
            sort=sort_spec,
        )
        return _strip_nan(doc) if doc else None

    async def read_latest_batch(
        self, market: str, domain: str, symbols: List[str],
        projection: Optional[Dict] = None,
    ) -> Dict[str, Dict]:
        """批量读取多只股票各自的最新一条记录，返回 {symbol: doc}。

        aggregate: $match $in → $sort 排序键 desc → $group symbol 取 $first。
        symbols 超过 MAX_BATCH_SYMBOLS(500) 时抛 ValueError（调用方应分批）。
        """
        symbols = list(symbols or [])
        if len(symbols) > self.MAX_BATCH_SYMBOLS:
            raise ValueError(
                f"symbols 数量 {len(symbols)} 超过上限 {self.MAX_BATCH_SYMBOLS}，请分批调用"
            )
        if not symbols:
            return {}

        sort_field = self._latest_sort_field(domain)
        pipeline: List[Dict] = [
            {"$match": {"symbol": {"$in": symbols}}},
            {"$sort": {sort_field: -1, "updated_at": -1}},
            {"$group": {"_id": "$symbol", "doc": {"$first": "$$ROOT"}}},
            {"$replaceRoot": {"newRoot": "$doc"}},
        ]
        proj = self._normalize_projection(projection)
        if proj != {"_id": 0}:
            # `symbol` 是下方组装返回值用的字典键（doc.get("symbol")）。投影若把它裁掉，
            # 该键恒为 None，所有文档会被静默丢弃 → 函数恒返回 {}（实测：调用方传
            # {close, pct_chg, trade_date} 时，自选页价格/涨跌幅永远为空）。
            if proj.get("symbol") != 0:
                proj = {**proj, "symbol": 1}
            pipeline.append({"$project": proj})

        coll = self._get_coll(market, domain)
        result: Dict[str, Dict] = {}
        async for doc in coll.aggregate(pipeline):
            s = doc.get("symbol")
            if s:
                result[s] = _strip_nan(doc)
        return result

    async def read_batch(
        self, market: str, domain: str, symbols: List[str],
        projection: Optional[Dict] = None,
        sort: Optional[List[Tuple[str, int]]] = None,
        limit: int = 0,
    ) -> List[Dict]:
        """批量读取多只股票的记录（不折叠为每股一条）。"""
        symbols = list(symbols or [])
        if not symbols:
            return []

        coll = self._get_coll(market, domain)
        cursor = coll.find(
            {"symbol": {"$in": symbols}},
            self._normalize_projection(projection),
        )
        if sort:
            cursor = cursor.sort(sort)
        if limit and limit > 0:
            cursor = cursor.limit(limit)
        docs = await cursor.to_list(length=None)
        return _strip_nan(docs)

    async def search_basic_info(
        self, market: str, query: str,
        fields: Optional[List[str]] = None,
        limit: int = 20,
    ) -> List[Dict]:
        """在 basic_info 中模糊搜索股票。

        symbol 字段按前缀匹配（^query），其余字段（name/name_en 等）按包含匹配；
        query 经 re.escape 转义，避免正则注入。
        """
        fields = fields or ["symbol", "name"]
        safe = re.escape(query)
        conditions = []
        for f in fields:
            pattern = f"^{safe}" if f == "symbol" else f".*{safe}.*"
            conditions.append({f: {"$regex": pattern, "$options": "i"}})

        coll = self._get_coll(market, "basic_info")
        cursor = coll.find({"$or": conditions}, {"_id": 0}).limit(limit)
        docs = await cursor.to_list(length=limit)
        return _strip_nan(docs)

    def _load_freshness_rules(self) -> Dict:
        """加载 freshness_rules.yaml，带 mtime 缓存。

        M8 修复：此前每次 check_freshness 都同步加载磁盘文件，在事件循环中
        产生阻塞。改为首次加载后缓存，通过 mtime 检查自动失效。
        """
        from app.data.config import load_yaml

        yaml_path = os.path.join(
            os.path.dirname(__file__), "..", "config", "freshness_rules.yaml"
        )
        try:
            mtime = os.path.getmtime(yaml_path)
        except OSError:
            mtime = 0

        with self._freshness_rules_lock:
            if (
                self._freshness_rules_cache is not None
                and mtime == self._freshness_rules_mtime
            ):
                return self._freshness_rules_cache
            rules = load_yaml("freshness_rules.yaml")
            self._freshness_rules_cache = rules
            self._freshness_rules_mtime = mtime
            return rules

    async def check_freshness(
        self, market: str, symbol: str, domain: str, data: Any = None
    ) -> str:
        """检查数据新鲜度。"""
        rules = self._load_freshness_rules()
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
            # 如果 updated_at 是 datetime 对象（第三方写入或迁移残留），
            # 直接使用；否则要求为 str 再做字符串操作，避免 .endswith 抛
            # AttributeError 且不被 except (ValueError, TypeError) 捕获。
            if isinstance(updated_at, datetime):
                updated = updated_at
            elif isinstance(updated_at, str):
                # Python 3.10 及更早版本的 datetime.fromisoformat 不支持 "Z" 后缀，
                # 需要先归一化；3.11+ 原生支持，这里统一兼容两种形式。
                iso_str = updated_at.replace("Z", "+00:00") if updated_at.endswith("Z") else updated_at
                updated = datetime.fromisoformat(iso_str)
            else:
                # int / float / None 等无法解析的类型
                return FreshnessState.UNKNOWN

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
                # 交易日语义判定：数据只要「覆盖到最近一个已收盘交易日」即 fresh。
                # 旧实现用 age < threshold_minutes 判定——周五收盘的数据周一必判
                # stale（跨周末 age 远超 30 分钟），语义错误。
                # 新实现：以记录的业务日期（trade_date 等）对照最近交易日；
                # 无业务日期字段时回退到「收盘后阈值 + 自然日预算」宽松判定，
                # 避免周末/节假日误报 stale。
                threshold_minutes = domain_rule.get("threshold_minutes", 60)
                record_date = None
                if isinstance(data, dict):
                    record_date = data.get("trade_date") or data.get("cal_date")
                elif isinstance(data, list) and data:
                    for d in reversed(data):
                        if isinstance(d, dict) and d.get("trade_date"):
                            record_date = d.get("trade_date")
                            break
                if record_date:
                    try:
                        from app.data.core.market import get_latest_trade_day

                        latest_td = await get_latest_trade_day(market)
                        if latest_td is not None:
                            # 记录业务日期 >= 最近交易日 → fresh（含今天已入库）
                            rec_d = str(record_date)[:10].replace("/", "-")
                            return (
                                FreshnessState.FRESH
                                if rec_d >= latest_td.isoformat()
                                else FreshnessState.STALE
                            )
                    except Exception:
                        pass  # 日历不可用时走下方时间兜底
                # 时间兜底：age 在阈值内 → fresh；超过阈值但未跨自然日预算
                # （收盘后数据跨周末属正常，72h 预算对齐 data_health 语义）
                age_minutes = (now - updated).total_seconds() / 60
                if age_minutes < threshold_minutes:
                    return FreshnessState.FRESH
                max_hours = domain_rule.get("max_stale_hours", 72)
                return (
                    FreshnessState.FRESH
                    if age_minutes < max_hours * 60
                    else FreshnessState.STALE
                )

        except (ValueError, TypeError, AttributeError):
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
