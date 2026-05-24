"""回退路由器 — 按优先级选择数据源，失败时降级。"""

import asyncio
import logging
import time
from typing import Dict, List, Optional

from app.data.processor.circuit_breaker import CircuitBreaker
from app.data.processor.rate_limiter import RateLimiter
from app.data.processor.retry_policy import RetryPolicy
from app.data.processor.normalizer import Normalizer
from app.data.processor.validator import Validator
from app.data.core.registry.capability import CapabilityRegistry
from app.data.core.registry.priority import PriorityConfig
from app.data.monitoring.source_health import SourceHealthMonitor
from app.data.sources.base.exceptions import DataSourceError
from app.data.sources.base.provider import BaseProvider

logger = logging.getLogger(__name__)


class FetchResult:
    """单次获取结果。"""
    def __init__(self):
        self.success: bool = False
        self.records: List[Dict] = []
        self.source: Optional[str] = None
        self.fallback_from: Optional[str] = None
        self.error: Optional[str] = None
        self.latency_ms: int = 0

    @property
    def data(self) -> List[Dict]:
        return self.records


class FallbackRouter:
    """回退路由器 — 选源 → 重试 → 降级 → 标准化 → 校验。"""

    def __init__(
        self,
        registry: CapabilityRegistry,
        priority: PriorityConfig,
        circuit_breaker: Optional[CircuitBreaker] = None,
        rate_limiter: Optional[RateLimiter] = None,
    ):
        self._registry = registry
        self._priority = priority
        self._circuit = circuit_breaker or CircuitBreaker()
        self._rate_limiter = rate_limiter or RateLimiter()
        self._normalizer = Normalizer()
        self._validator = Validator()
        self._health_monitor = SourceHealthMonitor()

    async def fetch(
        self, market: str, domain: str, symbol: str,
        start_date: str = "1970-01-01", end_date: str = "2099-12-31",
        preferred_sources: Optional[List[str]] = None,
    ) -> FetchResult:
        """从最优数据源获取并处理数据。"""
        result = FetchResult()
        start = time.time()

        priority_list = await self._priority.get_priority(market, domain)
        sources = self._registry.get_ordered_sources(market, domain, user_priority=priority_list)
        if preferred_sources:
            preferred_order = {name: i for i, name in enumerate(preferred_sources)}
            original_order = {name: i for i, name in enumerate(sources)}
            sources.sort(key=lambda name: (preferred_order.get(name, 999), original_order[name]))

        if not sources:
            result.error = f"无可用数据源: {market}/{domain}"
            return result

        fallback_chain = []
        default_exchange = {"CN": "SSE", "HK": "HKEX", "US": "NYSE"}.get(market, "SSE")

        for source_name in sources:
            if self._circuit.is_open(source_name, domain):
                logger.debug(f"熔断跳过: {source_name}/{domain}")
                continue

            allowed, wait = await self._rate_limiter.acquire(source_name, domain)
            if not allowed:
                await asyncio.sleep(wait)

            provider, adapter = await self._get_provider_adapter(market, source_name)
            if not provider or not adapter:
                continue

            retry_policy = RetryPolicy(max_retries=2)
            try:
                raw_data = await retry_policy.execute_with_retry(
                    self._fetch_raw, provider, domain, symbol, start_date, end_date, default_exchange
                )

                # 批量模式不支持 → 静默跳过，不记录失败
                if raw_data is self._BATCH_NOT_SUPPORTED:
                    logger.debug(f"源 {source_name}/{domain} 不支持批量模式，跳过")
                    continue

                if raw_data is None or (hasattr(raw_data, 'empty') and raw_data.empty):
                    self._circuit.record_failure(source_name, domain)
                    self._health_monitor.record_call(
                        market, source_name, domain, success=False,
                        latency_ms=int((time.time() - start) * 1000), error="empty data",
                        circuit_state=self._circuit.get_state(source_name, domain).value,
                    )
                    fallback_chain.append(source_name)
                    continue

                records = self._normalizer.normalize(raw_data, domain, adapter)
                if not records:
                    self._circuit.record_failure(source_name, domain)
                    self._health_monitor.record_call(
                        market, source_name, domain, success=False,
                        latency_ms=int((time.time() - start) * 1000), error="normalize empty",
                        circuit_state=self._circuit.get_state(source_name, domain).value,
                    )
                    fallback_chain.append(source_name)
                    continue

                valid, errors = self._validator.validate(records, domain, market)

                self._circuit.record_success(source_name, domain)
                result.latency_ms = int((time.time() - start) * 1000)
                self._health_monitor.record_call(
                    market, source_name, domain, success=True,
                    latency_ms=result.latency_ms,
                    circuit_state="closed",
                )
                result.success = True
                result.records = valid
                result.source = source_name
                if fallback_chain:
                    result.fallback_from = " → ".join(fallback_chain)
                return result

            except DataSourceError as e:
                self._circuit.record_failure(source_name, domain, e.code)
                self._health_monitor.record_call(
                    market, source_name, domain, success=False,
                    latency_ms=int((time.time() - start) * 1000), error=str(e),
                    circuit_state=self._circuit.get_state(source_name, domain).value,
                )
                fallback_chain.append(source_name)
                logger.warning(f"源 {source_name}/{domain} 失败: {e}")
            except Exception as e:
                self._circuit.record_failure(source_name, domain)
                self._health_monitor.record_call(
                    market, source_name, domain, success=False,
                    latency_ms=int((time.time() - start) * 1000), error=str(e),
                    circuit_state=self._circuit.get_state(source_name, domain).value,
                )
                fallback_chain.append(source_name)
                logger.warning(f"源 {source_name}/{domain} 异常: {e}")

        result.error = f"所有源失败: {', '.join(fallback_chain)}"
        result.latency_ms = int((time.time() - start) * 1000)
        return result

    async def _fetch_raw(self, provider, domain: str, symbol: str, start: str, end: str, exchange: str = "SSE"):
        method_map = {
            "basic_info": lambda: provider.get_stock_list(),
            "trade_calendar": lambda: provider.get_trade_calendar(exchange, start, end),
            "daily_quotes": lambda: provider.get_daily_quotes(symbol, start, end),
            "daily_indicators": lambda: self._fetch_daily_indicators(provider, symbol, start, end),
            "financial_data": lambda: provider.get_financial_data(symbol, start, end),
            "adj_factors": lambda: provider.get_adj_factors(symbol, start, end),
            "corporate_actions": lambda: provider.get_corporate_actions(symbol, start, end),
            "news": lambda: provider.get_news(symbol, start, end),
            "market_quotes": lambda: provider.get_market_quotes([symbol]),
            "intraday_quotes": lambda: provider.get_intraday_quotes(symbol, start, end),
            "money_flow": lambda: provider.get_money_flow(symbol, start, end),
            "margin_trading": lambda: provider.get_margin_trading(symbol, start, end),
            "dragon_tiger": lambda: provider.get_dragon_tiger(symbol, start, end),
            "block_trade": lambda: provider.get_block_trade(symbol, start, end),
        }
        method = method_map.get(domain)
        if method:
            return await method()
        return None

    # 批量模式不支持时返回此 sentinel，调用链应跳过而非记录失败
    _BATCH_NOT_SUPPORTED = object()

    async def _fetch_daily_indicators(self, provider, symbol: str, start: str, end: str):
        """获取每日指标：per-symbol 模式或按日期批量模式。"""
        if symbol == "__all__":
            # 批量同步模式：使用 trade_date 参数一次获取全市场
            # 仅当 provider 真正覆写了 get_daily_indicators_batch 才调用
            base_method = BaseProvider.get_daily_indicators_batch
            provider_method = type(provider).get_daily_indicators_batch
            if provider_method is base_method:
                # 未覆写 → 不支持批量模式
                return self._BATCH_NOT_SUPPORTED

            # 如果 end 是默认值（2099），使用今天日期
            from datetime import date
            trade_date = end if end != "2099-12-31" else date.today().strftime("%Y-%m-%d")
            return await provider.get_daily_indicators_batch(trade_date)
        return await provider.get_daily_indicators(symbol, start, end)

    async def _get_provider_adapter(self, market: str, source_name: str):
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
            logger.debug(f"获取 Provider/Adapter 失败: {e}")
        return None, None
