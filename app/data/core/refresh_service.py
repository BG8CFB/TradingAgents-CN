"""数据刷新服务 — 按需刷新指定股票数据。"""

import asyncio
import logging
import time
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, List, Optional, Tuple

from app.data.core.domain import DataDomain
from app.data.core.result import RefreshResult, DomainRefreshResult
from app.data.core.registry.capability import CapabilityRegistry
from app.data.core.registry.priority import PriorityConfig
from app.data.storage.redis.locks import DistributedLock
from app.data.storage.cache.memory_cache import TTLCache

if TYPE_CHECKING:
    from app.data.processor.fallback_router import FallbackRouter

logger = logging.getLogger(__name__)

_cooldown_cache = TTLCache(default_ttl=300)  # 5 分钟冷却
_SUPPORTED_ON_DEMAND_DOMAINS = {
    "basic_info",
    "trade_calendar",
    "daily_quotes",
    "daily_indicators",
    "adj_factors",
    "corporate_actions",
    "financial_data",
    "news",
    "market_quotes",
    # 分析前预拉取扩展域
    "intraday_quotes",
    "money_flow",
    "margin_trading",
    "dragon_tiger",
    "block_trade",
}

# 按日期增量刷新的域：{domain: (date_field, default_lookback_days)}
_INCREMENTAL_DOMAINS = {
    "daily_quotes": ("trade_date", 60),
    "daily_indicators": ("trade_date", 60),
    "adj_factors": ("trade_date", 60),
    "financial_data": ("report_period", 365),
    "intraday_quotes": ("datetime", 5),
    "money_flow": ("trade_date", 60),
    "margin_trading": ("trade_date", 60),
    "dragon_tiger": ("trade_date", 60),
    "block_trade": ("trade_date", 60),
    "corporate_actions": ("ex_date", 365),
    "news": ("publish_time", 7),
}


class DataRefreshService:
    """数据刷新服务 — 编排按需刷新流程。"""

    def __init__(self, capability_registry: CapabilityRegistry, priority_config: PriorityConfig):
        self._registry = capability_registry
        self._priority = priority_config
        self._router: Optional["FallbackRouter"] = None

    def _get_router(self):
        """获取或创建缓存的 FallbackRouter 实例（断路器和限流器状态跨调用保持）。

        使用进程级单例，与 sync_job / multi_source_basics_sync 共享状态。
        """
        if self._router is None:
            from app.data.processor.fallback_router import FallbackRouter
            self._router = FallbackRouter.get_instance()
        return self._router

    async def refresh(
        self,
        market: str,
        symbol: str,
        domains: Optional[List[str]] = None,
        force: bool = False,
        timeout: int = 30,
    ) -> RefreshResult:
        """刷新指定股票的数据。

        Args:
            market: 市场 (CN/HK/US)
            symbol: 股票代码
            domains: 要刷新的域列表（None = 全部）
            force: 是否强制刷新（忽略冷却期）
            timeout: 超时秒数

        Returns:
            RefreshResult 刷新结果
        """
        result = RefreshResult(symbol=symbol, market=market)
        start_time = time.time()

        if domains is None:
            domains = [d.value for d in DataDomain if d.value in _SUPPORTED_ON_DEMAND_DOMAINS]
        else:
            domains = list(domains)

        # 并行刷新各域
        tasks = []
        for domain in domains:
            tasks.append(self._refresh_domain(market, symbol, domain, force, timeout))

        domain_results = await asyncio.gather(*tasks, return_exceptions=True)

        for i, dr in enumerate(domain_results):
            if isinstance(dr, Exception):
                result.domains[domains[i]] = DomainRefreshResult(
                    domain=domains[i], status="failed", error=str(dr)
                )
            else:
                result.domains[domains[i]] = dr

        result.total_latency_ms = int((time.time() - start_time) * 1000)
        result.compute_status()
        return result

    async def _get_incremental_date_range(
        self, market: str, symbol: str, domain: str,
    ) -> Tuple[str, str]:
        """查询 MongoDB 最新记录，计算增量拉取的日期范围。

        Returns:
            (start_date, end_date) — start_date 为最新记录日期往前 7 天（重叠容错），
            end_date 为今天。若无历史数据则回退到默认 lookback。
        """
        date_field, default_lookback = _INCREMENTAL_DOMAINS[domain]

        try:
            from app.data.storage.mongo.client import get_motor_db
            from app.data.storage.mongo.collections import get_collection_name

            db = get_motor_db()
            coll_name = get_collection_name(domain, market)
            doc = await db[coll_name].find_one(
                {"symbol": symbol},
                {date_field: 1},
                sort=[(date_field, -1)],
            )

            if doc and doc.get(date_field):
                latest = doc[date_field]
                # 解析日期字符串，往前推 7 天作为重叠窗口
                if len(str(latest)) >= 10:
                    latest_date = datetime.strptime(str(latest)[:10], "%Y-%m-%d")
                else:
                    latest_date = datetime.strptime(str(latest), "%Y%m%d")
                start = (latest_date - timedelta(days=7)).strftime("%Y-%m-%d")
            else:
                start = (datetime.now(timezone.utc) - timedelta(days=default_lookback)).strftime("%Y-%m-%d")
        except Exception as e:
            logger.debug(f"查询最新日期失败，使用默认范围: {e}")
            start = (datetime.now(timezone.utc) - timedelta(days=default_lookback)).strftime("%Y-%m-%d")

        end = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        return start, end

    async def _refresh_domain(
        self, market: str, symbol: str, domain: str, force: bool, timeout: int
    ) -> DomainRefreshResult:
        """刷新单个域。"""
        start = time.time()
        dr = DomainRefreshResult(domain=domain, status="pending")

        if domain not in _SUPPORTED_ON_DEMAND_DOMAINS:
            dr.status = "failed"
            dr.error = f"按需刷新暂不支持该域: {domain}"
            dr.latency_ms = int((time.time() - start) * 1000)
            return dr

        # 冷却期检查
        cooldown_key = f"cooldown:{market}:{symbol}:{domain}"
        if not force and _cooldown_cache.get(cooldown_key):
            dr.status = "fresh"
            return dr

        # 获取分布式锁
        lock = DistributedLock(f"lock:{market}:{domain}:{symbol}", ttl=timeout)
        acquired = await lock.acquire_with_wait(max_wait=5)
        if not acquired:
            dr.status = "failed"
            dr.error = "获取刷新锁超时"
            dr.latency_ms = int((time.time() - start) * 1000)
            return dr

        try:
            router = self._get_router()

            # 增量域：只拉取最新记录之后的数据
            fetch_kwargs = {}
            if domain in _INCREMENTAL_DOMAINS:
                start_date, end_date = await self._get_incremental_date_range(market, symbol, domain)
                fetch_kwargs["start_date"] = start_date
                fetch_kwargs["end_date"] = end_date

            fetch_result = await asyncio.wait_for(
                router.fetch(market, domain, symbol, **fetch_kwargs),
                timeout=timeout,
            )

            if not fetch_result.success or not fetch_result.records:
                dr.status = "failed"
                dr.error = fetch_result.error or "所有数据源失败"
                dr.fallback_from = fetch_result.fallback_from
                dr.latency_ms = int((time.time() - start) * 1000)
                return dr

            count = await self._write_to_mongo(fetch_result.records, domain, market)

            dr.status = "refreshed"
            dr.source = fetch_result.source
            dr.fallback_from = fetch_result.fallback_from
            dr.record_count = count
            dr.latency_ms = int((time.time() - start) * 1000)

            _cooldown_cache.set(cooldown_key, True, ttl=300)
            return dr

        except asyncio.TimeoutError:
            dr.status = "timeout"
            dr.error = f"超时 ({timeout}s)"
            dr.latency_ms = int((time.time() - start) * 1000)
            return dr
        except Exception as e:
            logger.warning(f"刷新 {market}/{symbol}/{domain} 失败: {e}")
            dr.status = "failed"
            dr.error = str(e)
            dr.latency_ms = int((time.time() - start) * 1000)
            return dr

        finally:
            await lock.release()

    async def _write_to_mongo(self, records: list, domain: str, market: str) -> int:
        """写入 MongoDB。通过 DataInterface 单例获取 Reader，避免创建多余实例。"""
        try:
            from app.data.core.interface import DataInterface
            di = DataInterface.get_instance()
            repo = di.reader._get_repo(domain)
        except Exception as e:
            # 降级：直接创建（测试或特殊场景）
            logger.debug(f"通过 DataInterface 获取 Reader 失败，降级创建: {e}")
            from app.data.core.reader import Reader
            repo = Reader()._get_repo(domain)
        if repo:
            return await repo.upsert_many(records, market)
        return 0
