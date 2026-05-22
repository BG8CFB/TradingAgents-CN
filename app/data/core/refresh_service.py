"""数据刷新服务 — 按需刷新指定股票数据。"""

import asyncio
import logging
import time
from typing import List, Optional

from app.data.core.domain import DataDomain
from app.data.core.result import RefreshResult, DomainRefreshResult
from app.data.core.registry.capability import CapabilityRegistry
from app.data.core.registry.priority import PriorityConfig
from app.data.storage.redis.locks import DistributedLock
from app.data.storage.cache.memory_cache import TTLCache

logger = logging.getLogger(__name__)

_cooldown_cache = TTLCache(default_ttl=300)  # 5 分钟冷却


class DataRefreshService:
    """数据刷新服务 — 编排按需刷新流程。"""

    def __init__(self, capability_registry: CapabilityRegistry, priority_config: PriorityConfig):
        self._registry = capability_registry
        self._priority = priority_config

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
            domains = [d.value for d in DataDomain]

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

    async def _refresh_domain(
        self, market: str, symbol: str, domain: str, force: bool, timeout: int
    ) -> DomainRefreshResult:
        """刷新单个域。"""
        start = time.time()
        dr = DomainRefreshResult(domain=domain)

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
            # 获取优先级列表
            priority = await self._priority.get_priority(market, domain)

            # 获取候选源
            sources = self._registry.get_ordered_sources(market, domain, user_priority=priority)
            if not sources:
                dr.status = "failed"
                dr.error = "无可用数据源"
                return dr

            # 逐源尝试
            for source_name in sources:
                try:
                    provider, adapter = await self._get_provider_adapter(market, source_name)
                    if not provider or not adapter:
                        continue

                    raw_data = await asyncio.wait_for(
                        self._fetch_from_source(provider, domain, symbol),
                        timeout=timeout,
                    )

                    if raw_data is None:
                        continue

                    # 标准化
                    records = self._adapt_data(adapter, domain, raw_data)
                    if not records:
                        continue

                    # 校验
                    records = self._validate_records(records, domain, market)

                    # 写入 MongoDB
                    count = await self._write_to_mongo(records, domain, market)

                    dr.status = "refreshed"
                    dr.source = source_name
                    dr.record_count = count
                    dr.latency_ms = int((time.time() - start) * 1000)

                    # 设置冷却
                    _cooldown_cache.set(cooldown_key, True, ttl=300)
                    return dr

                except asyncio.TimeoutError:
                    dr.error = f"超时 ({timeout}s)"
                    continue
                except Exception as e:
                    logger.warning(f"刷新 {market}/{symbol}/{domain} 源 {source_name} 失败: {e}")
                    dr.fallback_from = source_name
                    dr.error = str(e)
                    continue

            dr.status = "failed"
            dr.error = dr.error or "所有数据源失败"
            dr.latency_ms = int((time.time() - start) * 1000)
            return dr

        finally:
            await lock.release()

    async def _get_provider_adapter(self, market: str, source_name: str):
        """获取数据源的 Provider 和 Adapter 实例。"""
        try:
            if market == "CN":
                from app.data.sources.cn import get_cn_provider, get_cn_adapter
                return get_cn_provider(source_name), get_cn_adapter(source_name)
            elif market == "HK":
                from app.data.sources.hk import get_hk_provider, get_hk_adapter
                return get_hk_provider(source_name), get_hk_adapter(source_name)
            elif market == "US":
                from app.data.sources.us import get_us_provider, get_us_adapter
                return get_us_provider(source_name), get_us_adapter(source_name)
        except Exception as e:
            logger.debug(f"获取 Provider/Adapter 失败 {market}/{source_name}: {e}")
        return None, None

    async def _fetch_from_source(self, provider, domain: str, symbol: str):
        """从 Provider 拉取原始数据。"""
        method_map = {
            "basic_info": provider.get_stock_list,
            "trade_calendar": provider.get_trade_calendar,
            "daily_quotes": provider.get_daily_quotes,
            "daily_indicators": provider.get_daily_indicators,
            "financial_data": provider.get_financial_data,
            "adj_factors": provider.get_adj_factors,
            "corporate_actions": provider.get_corporate_actions,
            "news": provider.get_news,
            "market_quotes": provider.get_market_quotes,
        }
        method = method_map.get(domain)
        if not method:
            return None

        if domain == "basic_info":
            return await method()
        elif domain == "market_quotes":
            return await method(symbols=[symbol])
        else:
            return await method(symbol=symbol, start_date="1970-01-01", end_date="2099-12-31")

    def _adapt_data(self, adapter, domain: str, raw_data) -> list:
        """调用 Adapter 标准化数据。"""
        method_map = {
            "basic_info": adapter.adapt_basic_info,
            "trade_calendar": adapter.adapt_trade_calendar,
            "daily_quotes": adapter.adapt_daily_quotes,
            "daily_indicators": adapter.adapt_daily_indicators,
            "financial_data": adapter.adapt_financial_data,
            "adj_factors": adapter.adapt_adj_factors,
            "corporate_actions": adapter.adapt_corporate_actions,
            "news": adapter.adapt_news,
            "market_quotes": adapter.adapt_market_quotes,
        }
        method = method_map.get(domain)
        if not method:
            return []

        try:
            records = method(raw_data)
            return [r.to_db_doc() for r in records]
        except Exception as e:
            logger.warning(f"标准化 {domain} 失败: {e}")
            return []

    def _validate_records(self, records: list, domain: str, market: str) -> list:
        """简单校验。"""
        valid = []
        for rec in records:
            if "symbol" not in rec:
                continue
            if domain not in ("basic_info", "trade_calendar") and "trade_date" not in rec:
                continue
            valid.append(rec)
        return valid

    async def _write_to_mongo(self, records: list, domain: str, market: str) -> int:
        """写入 MongoDB。"""
        from app.data.core.reader import Reader
        reader = Reader()
        repo = reader._get_repo(domain)
        if repo:
            return await repo.upsert_many(records, market)
        return 0
