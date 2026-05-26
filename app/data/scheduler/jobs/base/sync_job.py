"""通用同步任务基类 — 编排: 读检查点 → FallbackRouter.fetch → 写仓储 → 更新检查点 → 写 sync_event。"""

import logging
import time
from abc import ABC, abstractmethod
from datetime import datetime, timezone

from app.data.core.domain import DataDomain, MARKET_DATA_DOMAINS
from app.data.scheduler.checkpoint import CheckpointManager
from app.data.storage.mongo.repositories.metadata_repo import MetadataRepo

logger = logging.getLogger(__name__)
_SUPPORTED_SYNC_DOMAINS = {
    "basic_info",
    "trade_calendar",
    "daily_quotes",
    "daily_indicators",
    "adj_factors",
    "corporate_actions",
    "financial_data",
    "market_quotes",
    "news",
    "intraday_quotes",
    "money_flow",
    "margin_trading",
    "dragon_tiger",
    "block_trade",
    "tushare_universe",
}


class BaseSyncJob(ABC):
    """同步任务基类，三市场各域共用。"""

    def __init__(self, market: str, domain: str):
        self.market = market
        self.domain = domain
        self.sync_mode = "incremental"
        self.preferred_source = None
        self.dependencies = []
        self.force_sync = False
        self._checkpoint = CheckpointManager()
        self._metadata = MetadataRepo()

    async def execute(self) -> dict:
        """执行同步任务。"""
        start = time.time()
        event = {
            "event_type": "SYNC_START",
            "market": self.market,
            "domain": self.domain,
            "started_at": datetime.now(timezone.utc).isoformat(),
        }
        await self._metadata.insert_event(event)

        try:
            if self.domain not in _SUPPORTED_SYNC_DOMAINS:
                raise NotImplementedError(f"同步任务暂未打通该域: {self.market}/{self.domain}")

            # 非交易日跳过行情类数据（force_sync 时跳过检查）
            if not self.force_sync and DataDomain(self.domain) in MARKET_DATA_DOMAINS:
                if not await self._is_trading_day():
                    logger.info(f"非交易日，跳过 {self.market}/{self.domain}")
                    return {"status": "skipped", "reason": "non_trading_day"}

            # 读取检查点
            if self.sync_mode == "full":
                start_date = "1970-01-01"
            else:
                checkpoint = await self._checkpoint.get_checkpoint(
                    self.market, self.domain, "scheduled"
                )
                start_date = checkpoint or "1970-01-01"

            # 获取符号列表（basic_info/trade_calendar 不需要逐符号）
            symbols = await self._get_symbols() if self._needs_symbol_list() else ["__all__"]

            total_count = 0
            last_source = None

            from app.data.processor.fallback_router import FallbackRouter
            from app.data.core.registry.capability import CapabilityRegistry
            from app.data.core.registry.priority import PriorityConfig

            registry = CapabilityRegistry()
            priority = PriorityConfig()
            router = FallbackRouter(registry, priority)

            for symbol in symbols:
                result = await self._fetch_and_write(router, symbol, start_date)
                total_count += result.get("count", 0)
                last_source = result.get("source")

            # 更新检查点
            today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            await self._checkpoint.update_checkpoint(
                self.market, self.domain, "scheduled", today, total_count
            )

            elapsed = int((time.time() - start) * 1000)
            await self._metadata.insert_event({
                "event_type": "SYNC_SUCCESS",
                "market": self.market,
                "domain": self.domain,
                "source": last_source,
                "record_count": total_count,
                "latency_ms": elapsed,
            })

            return {"status": "success", "count": total_count, "latency_ms": elapsed}

        except Exception as e:
            elapsed = int((time.time() - start) * 1000)
            logger.error(f"同步失败 {self.market}/{self.domain}: {e}")
            await self._metadata.insert_event({
                "event_type": "SYNC_FAILED",
                "market": self.market,
                "domain": self.domain,
                "error": str(e),
                "latency_ms": elapsed,
            })
            return {"status": "failed", "error": str(e)}

    async def _fetch_and_write(self, router, symbol: str, start_date: str) -> dict:
        """通过 FallbackRouter 获取数据并写入。"""

        preferred_sources = [self.preferred_source] if self.preferred_source else None
        result = await router.fetch(
            self.market,
            self.domain,
            symbol,
            start_date,
            preferred_sources=preferred_sources,
        )

        if result.success and result.records:
            count = await self._write_records(result.records)
            return {"count": count, "source": result.source}
        return {"count": 0, "source": result.source, "error": result.error}

    async def _write_records(self, records: list) -> int:
        """写入仓储。"""
        from app.data.core.reader import Reader
        reader = Reader()
        repo = reader._get_repo(self.domain)
        if repo:
            return await repo.upsert_many(records, self.market)
        return 0

    async def _is_trading_day(self) -> bool:
        """查询交易日历。"""
        from app.data.core.market import is_trading_day
        return await is_trading_day(self.market)

    def _needs_symbol_list(self) -> bool:
        """是否需要逐符号同步。

        basic_info 和 trade_calendar 是全量同步。
        daily_indicators 使用按日期批量模式（trade_date 参数一次获取全市场）。
        market_quotes 使用批量快照模式。
        dragon_tiger / block_trade 按日期全量获取。
        """
        return self.domain not in (
            DataDomain.BASIC_INFO.value,
            DataDomain.TRADE_CALENDAR.value,
            DataDomain.MARKET_QUOTES.value,
            DataDomain.DAILY_INDICATORS.value,
            DataDomain.DRAGON_TIGER.value,
            DataDomain.BLOCK_TRADE.value,
        )

    async def _get_symbols(self) -> list:
        """获取当前市场活跃股票列表。"""
        from app.data.storage.mongo.repositories.basic_info_repo import BasicInfoRepo
        repo = BasicInfoRepo()
        stocks = await repo.get_active_symbols(self.market)
        symbols = [s["symbol"] for s in stocks]
        if not symbols:
            # 降级：list_status 字段可能缺失，改为获取所有记录
            from app.data.storage.mongo.client import get_motor_db
            from app.data.storage.mongo.collections import get_collection_name
            db = get_motor_db()
            coll = db[get_collection_name("basic_info", self.market)]
            cursor = coll.find({}, {"symbol": 1, "_id": 0})
            all_stocks = await cursor.to_list(length=None)
            symbols = [s["symbol"] for s in all_stocks if s.get("symbol")]
            logger.warning(f"list_status 字段缺失，降级获取全部股票: {len(symbols)} 只")
        return symbols

    @abstractmethod
    def get_cron(self) -> str:
        """返回 cron 表达式。"""
        ...

    @abstractmethod
    def get_timezone(self) -> str:
        """返回时区。"""
        ...
