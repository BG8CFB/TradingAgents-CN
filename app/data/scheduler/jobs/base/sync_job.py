"""通用同步任务基类 — 编排: 读检查点 → FallbackRouter.fetch → 写仓储 → 更新检查点 → 写 sync_event。"""

import asyncio
import logging
import time
from abc import ABC, abstractmethod
from datetime import datetime, timezone

from app.core.config import settings
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
    "connect_status",
    "southbound_holding",
    "pre_post_market",
}


def _resolve_sync_concurrency(market: str) -> int:
    """按市场读取并发上限（带兜底）。"""
    mapping = {
        "CN": "CN_SYNC_CONCURRENCY",
        "HK": "HK_SYNC_CONCURRENCY",
        "US": "US_SYNC_CONCURRENCY",
    }
    attr = mapping.get(market.upper(), "DATA_SYNC_CONCURRENCY")
    value = getattr(settings, attr, None)
    if isinstance(value, int) and value >= 1:
        return value
    return settings.DATA_SYNC_CONCURRENCY


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
                raise NotImplementedError(
                    f"同步任务暂未打通该域: {self.market}/{self.domain}"
                )

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
            symbols = (
                await self._get_symbols() if self._needs_symbol_list() else ["__all__"]
            )

            total_count = 0
            last_source = None

            # 使用进程级单例：与 refresh_service / multi_source_basics_sync
            # 共享 circuit_breaker + rate_limiter 状态
            from app.data.processor.fallback_router import FallbackRouter

            router = FallbackRouter.get_instance()

            # 关键：从串行 for 循环改为 Semaphore + gather 并发
            # - 单 symbol fetch 内部的 RateLimiter / CircuitBreaker 已是 asyncio.Lock 保护的并发安全状态
            # - Semaphore 不释放到 RateLimiter sleep 期间，保证 RateLimiter 窗口不被并发破坏
            # - return_exceptions=True 保证单个 symbol 失败不影响整体
            if len(symbols) <= 1:
                # 单 symbol 或 __all__：保持原串行路径，避免额外调度开销
                for symbol in symbols:
                    result = await self._fetch_and_write(router, symbol, start_date)
                    total_count += result.get("count", 0)
                    last_source = result.get("source")
            else:
                concurrency = _resolve_sync_concurrency(self.market)
                semaphore = asyncio.Semaphore(concurrency)
                logger.info(
                    f"并发同步 {self.market}/{self.domain}: symbols={len(symbols)} concurrency={concurrency}"
                )

                async def _limited_fetch(sym: str) -> dict:
                    async with semaphore:
                        return await self._fetch_and_write(router, sym, start_date)

                results = await asyncio.gather(
                    *[_limited_fetch(sym) for sym in symbols],
                    return_exceptions=True,
                )
                for sym, res in zip(symbols, results):
                    if isinstance(res, Exception):
                        logger.warning(
                            f"同步失败 {self.market}/{self.domain}/{sym}: {res}"
                        )
                        continue
                    total_count += res.get("count", 0)
                    src = res.get("source")
                    if src:
                        last_source = src

            # 更新检查点：用市场本地日期，避免跨时区边界日期错位
            from app.data.core.market import get_market_timezone

            market_tz = get_market_timezone(self.market)
            today = datetime.now(market_tz).strftime("%Y-%m-%d")
            await self._checkpoint.update_checkpoint(
                self.market, self.domain, "scheduled", today, total_count
            )

            elapsed = int((time.time() - start) * 1000)
            await self._metadata.insert_event(
                {
                    "event_type": "SYNC_SUCCESS",
                    "market": self.market,
                    "domain": self.domain,
                    "source": last_source,
                    "record_count": total_count,
                    "latency_ms": elapsed,
                }
            )

            return {"status": "success", "count": total_count, "latency_ms": elapsed}

        except Exception as e:
            elapsed = int((time.time() - start) * 1000)
            logger.error(f"同步失败 {self.market}/{self.domain}: {e}")
            await self._metadata.insert_event(
                {
                    "event_type": "SYNC_FAILED",
                    "market": self.market,
                    "domain": self.domain,
                    "error": str(e),
                    "latency_ms": elapsed,
                }
            )
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
        news 使用市场级抓取（全市场财经快讯，不依赖逐 symbol）。
        """
        return self.domain not in (
            DataDomain.BASIC_INFO.value,
            DataDomain.TRADE_CALENDAR.value,
            DataDomain.MARKET_QUOTES.value,
            DataDomain.DAILY_INDICATORS.value,
            DataDomain.DRAGON_TIGER.value,
            DataDomain.BLOCK_TRADE.value,
            DataDomain.NEWS.value,
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
