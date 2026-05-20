"""
A股按需刷新服务 (Data Refresh Service)

核心场景：分析引擎在执行分析前，确保指定股票的行情/指标/财务数据是最新的。

三种调用入口（共享同一套底层逻辑）：
  1. 内部服务调用：同步阻塞，等待刷新完成（核心入口）
  2. Reader 异步通知：读取时发现过期，后台静默刷新
  3. HTTP API：前端管理页面手动触发

特性：
  - 冷却期（5 分钟内不重复刷新）
  - 分布式锁（symbol + domain 粒度，进程内 asyncio.Lock）
  - 并行刷新多域
  - 30 秒超时兜底
"""

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set

from app.data.processor.circuit_breaker import CircuitBreaker
from app.data.processor.error_codes import DataErrorCode
from app.data.processor.fallback_router import FallbackRouter, FetchResult
from app.data.processor.capability_registry import CapabilityRegistry
from app.data.processor.rate_limiter import RateLimiter
from app.data.schema.collections import get_collection_name
from app.data.schema.sync_metadata import SyncEventSchema
from app.utils.time_utils import now_utc

logger = logging.getLogger(__name__)

# 默认刷新超时（秒）
DEFAULT_TIMEOUT = 30

# 冷却期（秒）
COOLDOWN_SECONDS = 300  # 5 分钟

# 全局刷新并发上限
MAX_CONCURRENT_REFRESH = 10


@dataclass
class DomainRefreshResult:
    """单个域的刷新结果"""
    domain: str
    status: str = "unknown"       # fresh / refreshed / partial / timeout / failed / skipped
    source: str = ""
    fallback_from: Optional[str] = None
    records: int = 0
    error: Optional[str] = None
    latency_ms: int = 0


@dataclass
class RefreshResult:
    """整体刷新结果"""
    symbol: str
    status: str = "unknown"       # fresh / refreshed / partial / timeout / failed
    domains: Dict[str, DomainRefreshResult] = field(default_factory=dict)
    duration_ms: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "symbol": self.symbol,
            "status": self.status,
            "domains": {
                d: {
                    "status": r.status,
                    "source": r.source,
                    "fallback_from": r.fallback_from,
                    "records": r.records,
                    "error": r.error,
                    "latency_ms": r.latency_ms,
                }
                for d, r in self.domains.items()
            },
            "duration_ms": self.duration_ms,
        }


class DataRefreshService:
    """
    A 股按需刷新服务

    使用方式：
        service = DataRefreshService()
        result = await service.refresh("000001", domains=["daily_quotes", "daily_indicators"])
    """

    def __init__(
        self,
        router: Optional[FallbackRouter] = None,
        cooldown_seconds: float = COOLDOWN_SECONDS,
        max_concurrent: int = MAX_CONCURRENT_REFRESH,
    ):
        self._router = router or FallbackRouter()
        self._cooldown_seconds = cooldown_seconds
        self._max_concurrent = max_concurrent

        # 进程内状态
        self._cooldowns: Dict[str, float] = {}          # "symbol:domain" → last_refresh_time
        self._locks: Dict[str, asyncio.Lock] = {}        # "symbol:domain" → Lock
        self._global_semaphore = asyncio.Semaphore(max_concurrent)
        self._providers: Optional[Dict[str, Any]] = None

    def _lock_key(self, symbol: str, domain: str) -> str:
        return f"{symbol}:{domain}"

    def _get_lock(self, symbol: str, domain: str) -> asyncio.Lock:
        key = self._lock_key(symbol, domain)
        if key not in self._locks:
            self._locks[key] = asyncio.Lock()
        return self._locks[key]

    def _is_in_cooldown(self, symbol: str, domain: str) -> bool:
        key = self._lock_key(symbol, domain)
        last = self._cooldowns.get(key, 0)
        return (time.monotonic() - last) < self._cooldown_seconds

    def _mark_refreshed(self, symbol: str, domain: str) -> None:
        key = self._lock_key(symbol, domain)
        self._cooldowns[key] = time.monotonic()

    async def _get_providers(self) -> Dict[str, Any]:
        """获取可用的 Provider 实例"""
        if self._providers is None:
            self._providers = {}
            try:
                from app.data.sources.cn.tushare.provider import TushareSourceProvider
                p = TushareSourceProvider()
                if p.is_available():
                    self._providers["tushare"] = p
            except Exception as e:
                logger.debug("Tushare provider 不可用: %s", e)

            try:
                from app.data.sources.cn.akshare.provider import AKShareSourceProvider
                p = AKShareSourceProvider()
                if await p.connect():
                    self._providers["akshare"] = p
            except Exception as e:
                logger.debug("AKShare provider 不可用: %s", e)

            try:
                from app.data.sources.cn.baostock.provider import BaoStockSourceProvider
                p = BaoStockSourceProvider()
                if await p.connect():
                    self._providers["baostock"] = p
            except Exception as e:
                logger.debug("BaoStock provider 不可用: %s", e)

        return self._providers

    async def _get_adapters(self) -> Dict[str, Any]:
        """获取可用的 Adapter 实例（与 Provider 对应）"""
        providers = await self._get_providers()
        adapters = {}
        try:
            from app.data.sources.cn.tushare.adapter import TushareAdapter
            if "tushare" in providers:
                adapters["tushare"] = TushareAdapter(provider=providers["tushare"])
        except Exception:
            pass
        try:
            from app.data.sources.cn.akshare.adapter import AKShareAdapter
            if "akshare" in providers:
                adapters["akshare"] = AKShareAdapter(provider=providers["akshare"])
        except Exception:
            pass
        try:
            from app.data.sources.cn.baostock.adapter import BaoStockAdapter
            if "baostock" in providers:
                adapters["baostock"] = BaoStockAdapter(provider=providers["baostock"])
        except Exception:
            pass
        return adapters

    async def refresh(
        self,
        symbol: str,
        domains: Optional[List[str]] = None,
        force: bool = False,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> RefreshResult:
        """
        刷新指定股票的数据。

        Args:
            symbol: 股票代码
            domains: 要刷新的数据域列表，None 表示全部
            force: 是否强制刷新（忽略冷却期）
            timeout: 超时时间（秒）

        Returns:
            RefreshResult 包含整体和各域刷新状态
        """
        start_time = time.monotonic()

        if domains is None:
            domains = [
                "daily_quotes", "daily_indicators", "adj_factors",
                "financial", "basic_info", "news",
            ]

        result = RefreshResult(symbol=symbol)

        # 并行刷新各域
        tasks = []
        for domain in domains:
            tasks.append(self._refresh_domain(symbol, domain, force, timeout))

        domain_results = await asyncio.gather(*tasks, return_exceptions=True)

        for domain, dr in zip(domains, domain_results):
            if isinstance(dr, Exception):
                result.domains[domain] = DomainRefreshResult(
                    domain=domain, status="failed", error=str(dr),
                )
            else:
                result.domains[domain] = dr

        result.duration_ms = int((time.monotonic() - start_time) * 1000)

        # 汇总状态
        result.status = self._aggregate_status(result.domains)

        # 写入 sync_event
        await self._write_refresh_event(symbol, result)

        return result

    async def _refresh_domain(
        self,
        symbol: str,
        domain: str,
        force: bool,
        timeout: float,
    ) -> DomainRefreshResult:
        """刷新单个域"""
        lock = self._get_lock(symbol, domain)

        # 冷却期检查
        if not force and self._is_in_cooldown(symbol, domain):
            return DomainRefreshResult(
                domain=domain, status="fresh",
                error="冷却期内跳过",
            )

        # 获取锁（带超时）
        try:
            await asyncio.wait_for(lock.acquire(), timeout=timeout)
        except asyncio.TimeoutError:
            return DomainRefreshResult(
                domain=domain, status="timeout",
                error="获取刷新锁超时",
            )

        try:
            async with self._global_semaphore:
                return await self._do_refresh_domain(symbol, domain, timeout)
        finally:
            lock.release()

    async def _do_refresh_domain(
        self, symbol: str, domain: str, timeout: float,
    ) -> DomainRefreshResult:
        """实际执行域刷新"""
        start_time = time.monotonic()
        providers = await self._get_providers()
        adapters = await self._get_adapters()

        try:
            fetch_result = await asyncio.wait_for(
                self._router.fetch(
                    domain, symbol=symbol, providers=providers,
                    adapters=adapters,
                ),
                timeout=timeout,
            )

            latency = int((time.monotonic() - start_time) * 1000)

            if fetch_result.success:
                # 写入 MongoDB
                records_written = await self._write_to_mongo(
                    domain, symbol, fetch_result.data, fetch_result.source,
                )

                self._mark_refreshed(symbol, domain)

                return DomainRefreshResult(
                    domain=domain,
                    status="refreshed",
                    source=fetch_result.source,
                    fallback_from=fetch_result.fallback_from,
                    records=records_written,
                    latency_ms=latency,
                )
            else:
                return DomainRefreshResult(
                    domain=domain,
                    status="failed",
                    source=fetch_result.source,
                    error=fetch_result.error,
                    latency_ms=latency,
                )

        except asyncio.TimeoutError:
            return DomainRefreshResult(
                domain=domain, status="timeout",
                error=f"刷新超时 ({timeout}s)",
                latency_ms=int((time.monotonic() - start_time) * 1000),
            )
        except Exception as e:
            return DomainRefreshResult(
                domain=domain, status="failed",
                error=str(e),
                latency_ms=int((time.monotonic() - start_time) * 1000),
            )

    async def _write_to_mongo(
        self, domain: str, symbol: str, data: Any, source: str,
    ) -> int:
        """将刷新的数据写入 MongoDB"""
        try:
            from app.core.database import get_database
            db = await get_database()
        except Exception:
            logger.warning("无法连接 MongoDB，跳过写入")
            return 0

        collection_name = get_collection_name("CN", domain)
        collection = db[collection_name]

        if data is None:
            return 0

        # 数据可能是 DataFrame 或 list
        import pandas as pd
        if isinstance(data, pd.DataFrame):
            if data.empty:
                return 0
            records = data.to_dict("records")
        elif isinstance(data, list):
            records = data
        elif isinstance(data, dict):
            records = [data]
        else:
            return 0

        if not records:
            return 0

        # 写入前校验
        from app.data.processor.validation import DataValidator
        validator = DataValidator()
        valid, invalid, errors = validator.validate_batch(domain, records)

        if not valid:
            logger.warning("域 %s 刷新数据全部校验失败: %d 条", domain, len(invalid))
            return 0

        if invalid:
            logger.info("域 %s 刷新数据 %d 条校验失败，写入 %d 条", domain, len(invalid), len(valid))

        # Upsert 写入
        try:
            from pymongo import UpdateOne

            operations = []
            for rec in valid:
                # 确定 filter
                filter_doc = {"symbol": rec.get("symbol", symbol)}
                if "trade_date" in rec:
                    filter_doc["trade_date"] = rec["trade_date"]
                if "report_period" in rec:
                    filter_doc["report_period"] = rec["report_period"]
                    filter_doc["statement_type"] = rec.get("statement_type", "indicator")

                rec["data_source"] = source
                rec["updated_at"] = now_utc().isoformat()

                operations.append(UpdateOne(filter_doc, {"$set": rec}, upsert=True))

            if operations:
                result = await collection.bulk_write(operations, ordered=False)
                return result.upserted_count + result.modified_count

        except Exception as e:
            logger.error("写入 %s 失败: %s", collection_name, e)

        return 0

    async def _write_refresh_event(self, symbol: str, result: RefreshResult) -> None:
        """写入刷新事件到 sync_events"""
        try:
            from app.core.database import get_database
            db = await get_database()
        except Exception:
            return

        collection = db[get_collection_name("CN", "sync_events")]

        for domain, dr in result.domains.items():
            event_type = {
                "fresh": "SYNC_SUCCESS",
                "refreshed": "SYNC_SUCCESS",
                "partial": "SYNC_SUCCESS",
                "timeout": "SYNC_FAILED",
                "failed": "SYNC_FAILED",
            }.get(dr.status, "SYNC_FAILED")

            event = {
                "event_type": event_type,
                "domain": domain,
                "source": dr.source,
                "symbol": symbol,
                "record_count": dr.records,
                "duration_ms": dr.latency_ms,
                "error_message": dr.error,
                "fallback_from": dr.fallback_from,
                "data_source": "refresh_service",
                "updated_at": now_utc().isoformat(),
            }

            try:
                await collection.insert_one(event)
            except Exception:
                pass

    @staticmethod
    def _aggregate_status(domains: Dict[str, DomainRefreshResult]) -> str:
        """汇总各域状态为整体状态"""
        if not domains:
            return "failed"

        statuses = {dr.status for dr in domains.values()}

        if all(s in ("fresh", "refreshed") for s in statuses):
            return "fresh" if statuses == {"fresh"} else "refreshed"

        if statuses.intersection({"timeout", "failed"}):
            if any(s in ("fresh", "refreshed") for s in statuses):
                return "partial"
            return "failed"

        return "partial"


# ── 单例 ──

_instance: Optional[DataRefreshService] = None


def get_refresh_service() -> DataRefreshService:
    """获取全局 DataRefreshService 单例"""
    global _instance
    if _instance is None:
        _instance = DataRefreshService()
    return _instance
