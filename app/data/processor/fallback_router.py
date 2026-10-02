"""回退路由器 — 按优先级选择数据源，失败时降级。"""

import asyncio
import logging
import threading
import time
from typing import Dict, List, Optional

from app.data.processor.circuit_breaker import (
    CircuitBreaker,
    load_source_cooldown_config,
)
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


# 进程级单例 — 同一进程内所有调用方共享同一份熔断器 / 限流器状态
_instance: Optional["FallbackRouter"] = None
_instance_lock = threading.Lock()


def _ensure_singleton() -> "FallbackRouter":
    """获取进程级 FallbackRouter 单例。

    所有调用方（refresh_service / sync_job / multi_source_basics_sync /
    domain_sync）共享同一份 circuit_breaker + rate_limiter 状态。
    """
    global _instance
    if _instance is None:
        with _instance_lock:
            if _instance is None:
                _instance = FallbackRouter(
                    CapabilityRegistry(),
                    PriorityConfig(),
                )
    return _instance


def reset_singleton() -> None:
    """测试场景下重置单例（生产代码不应调用）。"""
    global _instance
    with _instance_lock:
        _instance = None


class FetchResult:
    """单次获取结果。"""

    def __init__(self):
        self.success: bool = False
        self.records: List[Dict] = []
        self.source: Optional[str] = None
        self.fallback_from: Optional[str] = None
        self.error: Optional[str] = None
        self.latency_ms: int = 0
        self.validation_errors: Optional[Dict] = None

    @property
    def data(self) -> List[Dict]:
        return self.records


class FallbackRouter:
    """回退路由器 — 选源 → 重试 → 降级 → 标准化 → 校验。

    建议使用 ``FallbackRouter.get_instance()`` 获取进程级单例，
    以便与 sync_job / refresh_service 等调用方共享熔断器与限流器状态。

    Note:
        单例状态保存在模块级 ``_instance`` / ``_instance_lock``（见文件顶部），
        类内部不再重复定义，避免双状态分裂。
    """

    def __init__(
        self,
        registry: CapabilityRegistry,
        priority: PriorityConfig,
        circuit_breaker: Optional[CircuitBreaker] = None,
        rate_limiter: Optional[RateLimiter] = None,
        retry_max_retries: int = 2,
    ):
        self._registry = registry
        self._priority = priority
        self._circuit = circuit_breaker or self._create_default_circuit_breaker()
        self._rate_limiter = rate_limiter or self._create_default_rate_limiter()
        self._normalizer = Normalizer()
        self._validator = Validator()
        self._health_monitor = SourceHealthMonitor()
        self._retry_max_retries = retry_max_retries
        # 源级重试配置（source_limits.yaml 的 retry: 块）；优先于全局默认
        self._retry_config: Dict[str, dict] = self._load_retry_config()

    @classmethod
    def get_instance(cls) -> "FallbackRouter":
        """获取进程级单例（首次调用时构造，后续复用）。

        保证 sync_job、refresh_service、multi_source_basics_sync、
        domain_sync 等所有调用方共享同一份熔断器 + 限流器状态。
        """
        return _ensure_singleton()

    @classmethod
    def reset_instance(cls) -> None:
        """重置单例（仅测试用）。"""
        reset_singleton()

    @staticmethod
    def _create_default_circuit_breaker() -> CircuitBreaker:
        """从 source_limits.yaml 加载熔断冷却阶梯并构造 CircuitBreaker。"""
        try:
            steps_by_source = load_source_cooldown_config()
        except Exception as e:
            logger.warning(f"加载熔断冷却配置失败，使用默认阶梯: {e}")
            steps_by_source = {}
        return CircuitBreaker(source_cooldown_config=steps_by_source)

    @staticmethod
    def _create_default_rate_limiter() -> RateLimiter:
        """从 source_limits.yaml 加载限流配置。

        YAML 加载失败时 fail-safe 回退到 source_metadata（与 YAML 同源解析，
        含各字段默认值），不再维护与 YAML 漂移的硬编码兜底。
        """
        limiter = RateLimiter()

        try:
            from app.data.core.registry.source_metadata import SOURCE_METADATA

            for source, meta in SOURCE_METADATA.items():
                limiter.configure(
                    source,
                    rate_per_minute=meta.rate_per_minute,
                    polite_interval_ms=meta.polite_interval_ms,
                    rate_per_day=meta.rate_per_day,
                )
        except Exception as e:
            logger.warning(f"加载限流配置失败: {e}")

        return limiter

    @staticmethod
    def _load_retry_config() -> Dict[str, dict]:
        """从 source_limits.yaml 读取每个源的重试配置。

        YAML 字段（source 级）::

            retry:
              max_retries: 2
              backoff_base: 1.0

        读取失败返回空 dict，调用方回退到构造参数的全局默认值。
        """
        import yaml
        from pathlib import Path

        config_path = Path(__file__).parent.parent / "config" / "source_limits.yaml"
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                limits_config = yaml.safe_load(f) or {}
        except Exception as e:
            logger.warning(f"加载重试配置失败，使用全局默认: {e}")
            return {}

        result: Dict[str, dict] = {}
        for source, cfg in limits_config.items():
            if not isinstance(cfg, dict):
                continue
            retry = cfg.get("retry")
            if isinstance(retry, dict):
                result[source] = {
                    "max_retries": int(retry.get("max_retries", 2)),
                    "backoff_base": float(retry.get("backoff_base", 1.0)),
                }
        return result

    async def fetch(
        self,
        market: str,
        domain: str,
        symbol: str,
        start_date: str = "1970-01-01",
        end_date: str = "2099-12-31",
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
            sources.sort(
                key=lambda name: (
                    preferred_order.get(name, 999),
                    original_order.get(name, 999),
                )
            )

        if not sources:
            result.error = f"无可用数据源: {market}/{domain}"
            return result

        fallback_chain = []
        default_exchange = {"CN": "SSE", "HK": "HKEX", "US": "NYSE"}.get(market, "SSE")

        for source_name in sources:
            status, records, verrs = await self.fetch_source(
                market, domain, source_name,
                lambda p: self._fetch_raw(
                    p, domain, symbol, start_date, end_date, default_exchange
                ),
            )
            if status == "failed":
                fallback_chain.append(source_name)
                continue
            if status == "skip":
                continue

            result.success = True
            result.records = records
            result.source = source_name
            result.latency_ms = int((time.time() - start) * 1000)
            if verrs:
                result.validation_errors = verrs
            if fallback_chain:
                result.fallback_from = " → ".join(fallback_chain)
            return result

        result.error = f"所有源失败: {', '.join(fallback_chain)}"
        result.latency_ms = int((time.time() - start) * 1000)
        return result

    async def fetch_source(
        self,
        market: str,
        domain: str,
        source_name: str,
        raw_fetch,
    ):
        """单数据源尝试：熔断检查 → 限流 → 重试获取 → 标准化 → 校验。

        从 fetch() 的循环体抽取，供两类调用方复用同一套四件套语义：
        1. fetch() 内部（标准 symbol 维度获取）
        2. worker 侧 BaseMarketDomainSync（自定义 provider 方法 + kwargs 的
           批量域同步，如 HK/US market_quotes 全市场快照）

        Args:
            raw_fetch: ``async (provider) -> raw``，返回原始数据；
                返回 ``_BATCH_NOT_SUPPORTED`` 哨兵表示源不支持该调用形态。

        Returns:
            (status, records, validation_errors)
            status: "success" / "failed"（已记熔断失败，应尝试次源）/
            "skip"（源不可用或不支持，静默跳过，不计失败）
        """
        source_start = time.time()

        if self._circuit.is_open(source_name, domain=domain, market=market):
            logger.debug(f"熔断跳过: {source_name}/{domain}")
            return "skip", [], None

        allowed, wait = await self._rate_limiter.acquire(source_name, domain)
        if not allowed:
            await asyncio.sleep(wait)
            # 等待期间熔断可能已被其他调用方触发；此时不应消耗已扣配额，归还之
            if self._circuit.is_open(source_name, domain=domain, market=market):
                await self._rate_limiter.release(source_name, domain)
                return "skip", [], None

        # M6 修复：acquire 成功后再检查一次熔断状态。
        # acquire 和 provider 调用之间有 await 切换点，其他协程可能在此期间
        # 触发熔断。虽然 Python 单线程 async 中该窗口很短，但若不检查会浪费
        # rate_limiter 配额（已扣配额但请求必然被熔断拒绝）。
        if self._circuit.is_open(source_name, domain=domain, market=market):
            await self._rate_limiter.release(source_name, domain)
            return "skip", [], None

        provider, adapter = await self._get_provider_adapter(market, source_name)
        if not provider or not adapter:
            # R13-DS-05 修复：provider/adapter 获取失败时清除探测许可标记，
            # 防止 _probe_granted 永久残留导致熔断器被永久禁用。
            self._circuit.clear_probe(source_name, domain=domain, market=market)
            return "skip", [], None

        retry_cfg = self._retry_config.get(source_name, {})
        retry_policy = RetryPolicy(
            max_retries=retry_cfg.get("max_retries", self._retry_max_retries),
            backoff_base=retry_cfg.get("backoff_base", 1.0),
        )
        try:
            raw_data = await retry_policy.execute_with_retry(raw_fetch, provider)

            # 批量模式不支持 → 静默跳过，不记录失败
            if raw_data is self._BATCH_NOT_SUPPORTED:
                logger.debug(f"源 {source_name}/{domain} 不支持批量模式，跳过")
                # R13-DS-05 修复：清除探测许可标记，防止 _probe_granted 残留。
                self._circuit.clear_probe(source_name, domain=domain, market=market)
                return "skip", [], None

            if raw_data is None or (hasattr(raw_data, "empty") and raw_data.empty):
                self._circuit.record_failure(source_name, domain=domain, market=market)
                self._health_monitor.record_call(
                    market,
                    source_name,
                    domain,
                    success=False,
                    latency_ms=int((time.time() - source_start) * 1000),
                    error="empty data",
                    circuit_state=self._circuit.get_state(source_name, domain=domain, market=market).value,
                )
                return "failed", [], None

            # M1 修复：区分"adapter 不支持该域"与"数据质量差"。
            # 不支持的域不应触发熔断。
            # normalize/validate 内部是 pandas 逐行处理（iterrows 等 CPU 密集逻辑），
            # 直接跑在事件循环上会在全量同步期间阻塞所有并发请求 → 卸载到线程池
            normalize_result = await asyncio.to_thread(
                self._normalizer.normalize_with_status, raw_data, domain, adapter
            )
            records = normalize_result.records
            if not records:
                if normalize_result.status == "error":
                    self._circuit.record_failure(source_name, domain=domain, market=market)
                self._health_monitor.record_call(
                    market,
                    source_name,
                    domain,
                    success=normalize_result.status != "error",
                    latency_ms=int((time.time() - source_start) * 1000),
                    error=f"normalize {normalize_result.status}",
                    circuit_state=self._circuit.get_state(source_name, domain=domain, market=market).value,
                )
                return "failed", [], None

            valid, errors = await asyncio.to_thread(
                self._validator.validate, records, domain, market
            )

            # 校验剔除的记录不等于源故障：仍记 success，但记录 warning 供排查
            dropped = len(records) - len(valid)
            if errors:
                logger.warning(
                    "数据校验剔除 %d/%d 条记录: market=%s domain=%s source=%s errors=%s",
                    dropped,
                    len(records),
                    market,
                    domain,
                    source_name,
                    errors[:5],
                )

            self._circuit.record_success(source_name, domain=domain, market=market)
            self._health_monitor.record_call(
                market,
                source_name,
                domain,
                success=True,
                latency_ms=int((time.time() - source_start) * 1000),
                circuit_state="closed",
            )
            validation_errors = None
            if errors:
                validation_errors = {
                    "dropped": dropped,
                    "total": len(records),
                    "samples": errors[:5],
                }
            return "success", valid, validation_errors

        except DataSourceError as e:
            self._circuit.record_failure(source_name, domain=domain, market=market, error_code=e.code)
            self._health_monitor.record_call(
                market,
                source_name,
                domain,
                success=False,
                latency_ms=int((time.time() - source_start) * 1000),
                error=str(e),
                circuit_state=self._circuit.get_state(source_name, domain=domain, market=market).value,
            )
            logger.warning(f"源 {source_name}/{domain} 失败: {e}")
            return "failed", [], None
        except NotImplementedError as e:
            # 源不支持该域（Provider 未覆写基类方法）：静默跳过，不记录失败
            # 避免错误地影响断路器状态和重试逻辑
            logger.debug(f"源 {source_name}/{domain} 不支持该域，跳过: {e}")
            # R13-DS-05 修复：清除探测许可标记，防止 _probe_granted 残留。
            self._circuit.clear_probe(source_name, domain=domain, market=market)
            return "skip", [], None
        except Exception as e:
            self._circuit.record_failure(source_name, domain=domain, market=market)
            self._health_monitor.record_call(
                market,
                source_name,
                domain,
                success=False,
                latency_ms=int((time.time() - source_start) * 1000),
                error=str(e),
                circuit_state=self._circuit.get_state(source_name, domain=domain, market=market).value,
            )
            logger.warning(f"源 {source_name}/{domain} 异常: {e}")
            return "failed", [], None

    async def _fetch_raw(
        self,
        provider,
        domain: str,
        symbol: str,
        start: str,
        end: str,
        exchange: str = "SSE",
    ):
        method_map = {
            "basic_info": lambda: provider.get_stock_list(),
            "trade_calendar": lambda: provider.get_trade_calendar(exchange, start, end),
            "daily_quotes": lambda: provider.get_daily_quotes(symbol, start, end),
            "daily_indicators": lambda: self._fetch_daily_indicators(provider, symbol, start, end),
            "financial_data": lambda: self._fetch_financial_batch(provider, symbol, start, end),
            "adj_factors": lambda: provider.get_adj_factors(symbol, start, end),
            "corporate_actions": lambda: provider.get_corporate_actions(symbol, start, end),
            "news": lambda: provider.get_news(None if symbol == "__all__" else symbol, start, end),
            "market_quotes": lambda: provider.get_market_quotes([symbol]),
            "intraday_quotes": lambda: provider.get_intraday_quotes(symbol, start, end),
            "money_flow": lambda: self._fetch_money_flow_batch(provider, symbol, start, end),
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

    async def _fetch_financial_batch(self, provider, symbol: str, start: str, end: str):
        """获取财务数据：per-symbol 模式或按报告期批量模式（一次全市场）。

        逐 symbol 对全市场不可行（~5400 股 × 多表在限流下必熔断）；
        报告期窗口由 provider 实现自决（如最近 5 期，每日重拉覆盖迟披露）。
        """
        if symbol != "__all__":
            return await provider.get_financial_data(symbol, start, end)
        base_method = BaseProvider.get_financial_data_batch
        if type(provider).get_financial_data_batch is base_method:
            return self._BATCH_NOT_SUPPORTED
        return await provider.get_financial_data_batch()

    async def _fetch_money_flow_batch(self, provider, symbol: str, start: str, end: str):
        """获取资金流向：per-symbol 模式或按交易日批量模式。

        批量拉最近 6 个交易日（引擎资金窗口 5 日 + 1 日冗余）：当日发布
        延迟或某日失败可由次日窗口自愈，首次部署即完成引擎窗口回填，
        无需独立回填脚本。单日无数据（停市/未发布）跳过不阻塞其他日。
        """
        if symbol != "__all__":
            return await provider.get_money_flow(symbol, start, end)
        base_method = BaseProvider.get_money_flow_batch
        if type(provider).get_money_flow_batch is base_method:
            return self._BATCH_NOT_SUPPORTED

        from app.data.sources.base.exceptions import DataNotFoundError

        dates = await self._recent_quote_trade_dates(provider.market, 6)
        if not dates:
            return self._BATCH_NOT_SUPPORTED  # 本地无行情日期，skip 不误记熔断

        import pandas as pd

        frames = []
        for d in dates:
            try:
                df = await provider.get_money_flow_batch(d)
            except DataNotFoundError:
                logger.debug(f"{provider.name} money_flow {d} 无数据，跳过")
                continue
            if df is not None and not df.empty:
                frames.append(df)
        if not frames:
            return pd.DataFrame()
        return pd.concat(frames, ignore_index=True)

    async def _recent_quote_trade_dates(self, market: str, n: int) -> List[str]:
        """从 daily_quotes 取最近 n 个交易日（降序）——批量资金流日期窗口来源。"""
        from app.data.storage.mongo.client import get_motor_db
        from app.data.storage.mongo.collections import get_collection_name

        db = get_motor_db()
        distinct = await db[get_collection_name("daily_quotes", market)].distinct(
            "trade_date"
        )
        return sorted([d for d in distinct if d], reverse=True)[:n]

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
