"""
回退路由器 (Fallback Router)

核心职责：为每次数据请求选择最优数据源，处理重试和降级。

流程：查询能力注册表 → 按用户优先级排序 → 过滤熔断源 → 尝试调用
      → 可重试错误：指数退避重试 → 不可重试错误：立即降级到下一源
"""

import asyncio
import logging
import time
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

from .capability_registry import CapabilityRegistry, SupportLevel
from .circuit_breaker import CircuitBreaker
from .error_codes import DataErrorCode
from .rate_limiter import RateLimiter

logger = logging.getLogger(__name__)


class ErrorCategory(str, Enum):
    """错误分类：决定是重试还是降级"""
    # 可重试错误
    RATE_LIMITED = "rate_limited"       # HTTP 429
    NETWORK_TIMEOUT = "network"         # 网络超时
    CONNECTION_ERROR = "connection"      # 连接断开

    # 不可重试错误
    AUTH_FAILED = "auth_failed"          # HTTP 403
    SERVER_ERROR = "server_error"        # HTTP 5xx
    DATA_INVALID = "data_invalid"        # 数据格式异常
    EMPTY_RESULT = "empty_result"        # 空结果

    # 未知
    UNKNOWN = "unknown"


# 可重试错误 → 退避策略（秒）
_RETRYABLE_ERRORS = {
    ErrorCategory.RATE_LIMITED: [3.0, 10.0],
    ErrorCategory.NETWORK_TIMEOUT: [5.0, 15.0],
    ErrorCategory.CONNECTION_ERROR: [2.0, 5.0],
}

# 不可重试错误 → 映射到熔断器错误类型
_CIRCUIT_ERROR_MAP = {
    ErrorCategory.AUTH_FAILED: "auth_failed",
    ErrorCategory.SERVER_ERROR: "server_error",
    ErrorCategory.RATE_LIMITED: "rate_limited",
    ErrorCategory.NETWORK_TIMEOUT: "network",
    ErrorCategory.CONNECTION_ERROR: "network",
}


@dataclass
class FetchResult:
    """单次数据获取的结果"""
    success: bool = False
    data: Any = None
    source: str = ""
    domain: str = ""
    error: Optional[str] = None
    error_category: Optional[ErrorCategory] = None
    fallback_from: Optional[str] = None   # 回退来源
    attempts: int = 0                      # 尝试次数
    latency_ms: int = 0                    # 总耗时


@dataclass
class ProviderCallResult:
    """Provider 调用返回的中间结果"""
    success: bool
    data: Any = None
    error: Optional[str] = None
    error_category: Optional[ErrorCategory] = None
    latency_ms: int = 0


class FallbackRouter:
    """
    回退路由器：数据源选择 + 重试 + 降级

    使用方式：
      router = FallbackRouter(registry, circuit_breaker, rate_limiter)
      result = await router.fetch("daily_quotes", symbol="000001", ...)
    """

    # source_health 滑动窗口大小（保留最近 N 次调用记录）
    _HEALTH_WINDOW_SIZE = 100

    def __init__(
        self,
        registry: Optional[CapabilityRegistry] = None,
        circuit_breaker: Optional[CircuitBreaker] = None,
        rate_limiter: Optional[RateLimiter] = None,
        max_retries: int = 2,
    ):
        self.registry = registry or CapabilityRegistry()
        self.circuit_breaker = circuit_breaker or CircuitBreaker()
        self.rate_limiter = rate_limiter or RateLimiter()
        self.max_retries = max_retries

        # 进程内 source_health 滑动窗口: (source, domain) → deque of _HealthSample
        self._health_samples: Dict[tuple, deque] = {}
        self._health_write_counter: int = 0
        # 每 20 次 fetch 写一次 MongoDB（减少写入频率）
        self._health_flush_interval: int = 20

    async def fetch(
        self,
        domain: str,
        symbol: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        trade_date: Optional[str] = None,
        providers: Optional[Dict[str, Any]] = None,
        user_priority: Optional[List[str]] = None,
        disabled_sources: Optional[List[str]] = None,
        adapters: Optional[Dict[str, Any]] = None,
    ) -> FetchResult:
        """
        执行带回退的数据获取。

        Args:
            domain: 数据域
            symbol: 股票代码
            providers: 可用的 Provider 实例 {source_name: provider}
            user_priority: 用户自定义优先级
            disabled_sources: 被禁用的数据源
            adapters: 可用的 Adapter 实例 {source_name: adapter}，用于标准化

        Returns:
            FetchResult 包含获取结果或错误信息
        """
        start_time = time.monotonic()
        providers = providers or {}
        adapters = adapters or {}

        # 1. 获取候选源列表
        candidates = self.registry.get_ordered_sources(
            domain, user_priority=user_priority, disabled_sources=disabled_sources,
        )

        if not candidates:
            return FetchResult(
                success=False, domain=domain,
                error="所有数据源不可用",
                error_category=ErrorCategory.UNKNOWN,
            )

        # 2. 过滤熔断的源
        available = [
            src for src in candidates
            if not self.circuit_breaker.is_open(src, domain)
        ]

        if not available:
            return FetchResult(
                success=False, domain=domain,
                error=f"所有候选源已熔断: {candidates}",
                error_category=ErrorCategory.UNKNOWN,
            )

        # 3. 逐源尝试
        last_result = None
        fallback_from = None

        for source in available:
            provider = providers.get(source)
            if not provider:
                logger.debug("跳过 %s: 无 Provider 实例", source)
                continue

            # 限流检查
            allowed, wait_seconds = await self.rate_limiter.acquire(source, domain)
            if not allowed:
                logger.debug("限流等待 %.1fs: %s/%s", wait_seconds, source, domain)
                await asyncio.sleep(wait_seconds)

            # 尝试调用（含重试）
            result = await self._try_source(
                provider, source, domain,
                symbol=symbol, start_date=start_date, end_date=end_date,
                trade_date=trade_date, adapter=adapters.get(source),
            )
            last_result = result
            result.fallback_from = fallback_from

            if result.success:
                # 成功 → 更新熔断器 + 记录健康 + 返回
                self.circuit_breaker.record_success(source, domain)
                self._record_health_sample(source, domain, success=True,
                                           latency_ms=result.latency_ms)
                result.latency_ms = int((time.monotonic() - start_time) * 1000)
                return result

            # 失败 → 记录 + 尝试下一源
            error_type = _CIRCUIT_ERROR_MAP.get(
                result.error_category or ErrorCategory.UNKNOWN, "network",
            )
            self.circuit_breaker.record_failure(source, domain, error_type)
            self._record_health_sample(source, domain, success=False,
                                       latency_ms=result.latency_ms,
                                       error=result.error)
            fallback_from = source
            logger.warning(
                "数据源 %s 域 %s 失败: %s (尝试 %d 次)",
                source, domain, result.error, result.attempts,
            )

        # 所有源都失败
        if last_result:
            last_result.latency_ms = int((time.monotonic() - start_time) * 1000)
            return last_result

        return FetchResult(
            success=False, domain=domain,
            error="无可用 Provider 实例",
            error_category=ErrorCategory.UNKNOWN,
            latency_ms=int((time.monotonic() - start_time) * 1000),
        )

    async def _try_source(
        self,
        provider: Any,
        source: str,
        domain: str,
        symbol: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        trade_date: Optional[str] = None,
        adapter: Optional[Any] = None,
    ) -> FetchResult:
        """尝试单个数据源（含重试逻辑）"""
        attempts = 0
        last_error = None
        last_category = None

        for attempt in range(self.max_retries + 1):
            attempts += 1
            call_start = time.monotonic()

            try:
                raw_data = await self._call_provider(
                    provider, domain,
                    symbol=symbol, start_date=start_date, end_date=end_date,
                    trade_date=trade_date,
                )
                latency = int((time.monotonic() - call_start) * 1000)

                if raw_data is not None:
                    # 通过 Adapter 标准化
                    standardized = self._adapt_data(raw_data, domain, adapter)

                    return FetchResult(
                        success=True, data=standardized,
                        source=source, domain=domain,
                        attempts=attempts, latency_ms=latency,
                    )

                # 空结果
                last_error = "数据源返回空数据"
                last_category = ErrorCategory.EMPTY_RESULT

            except Exception as e:
                latency = int((time.monotonic() - call_start) * 1000)
                last_error = str(e)
                last_category = self._classify_error(e)

            # 判断是否可重试
            if last_category in _RETRYABLE_ERRORS and attempt < self.max_retries:
                backoff = _RETRYABLE_ERRORS[last_category][min(attempt - 1, 1)]
                logger.info(
                    "重试 %s/%s (第 %d 次, 等待 %.1fs): %s",
                    source, domain, attempt + 1, backoff, last_error,
                )
                await asyncio.sleep(backoff)
            else:
                break

        return FetchResult(
            success=False, source=source, domain=domain,
            error=last_error, error_category=last_category,
            attempts=attempts,
        )

    async def _call_provider(
        self,
        provider: Any,
        domain: str,
        symbol: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        trade_date: Optional[str] = None,
    ) -> Any:
        """调用 Provider 的对应方法"""
        dispatch = {
            "basic_info": lambda: provider.get_stock_basic_info(symbol),
            "trade_calendar": lambda: provider.get_trade_calendar(
                exchange="SSE", start_date=start_date, end_date=end_date,
            ),
            "daily_quotes": lambda: provider.get_daily_quotes(
                symbol, start_date, end_date,
            ),
            "daily_indicators": lambda: provider.get_daily_indicators(
                trade_date=trade_date, symbol=symbol,
            ),
            "adj_factors": lambda: provider.get_adj_factors(
                symbol, start_date, end_date,
            ),
            "financial": lambda: provider.get_financial_data(symbol),
            "market_quotes": lambda: provider.get_realtime_quotes(),
            "news": lambda: provider.get_news(symbol=symbol),
        }

        handler = dispatch.get(domain)
        if handler is None:
            raise ValueError(f"不支持的数据域: {domain}")

        result = handler()
        # Provider 方法可能是 async
        if asyncio.iscoroutine(result):
            result = await result
        return result

    @staticmethod
    def _adapt_data(raw_data: Any, domain: str, adapter: Optional[Any] = None) -> Any:
        """
        通过 Adapter 将 Provider 原始数据转换为标准化格式。

        如果没有传入 adapter，则返回原始数据（向后兼容）。
        如果适配失败，也返回原始数据（不阻塞主流程）。
        """
        if adapter is None:
            return raw_data

        import pandas as pd

        try:
            # DataFrame → 逐行适配 → 返回 dict 列表
            if isinstance(raw_data, pd.DataFrame):
                if raw_data.empty:
                    return raw_data

                domain_method_map = {
                    "basic_info": "adapt_basic_info_batch",
                    "daily_quotes": "adapt_daily_quote_batch",
                    "daily_indicators": "adapt_daily_indicators_batch",
                    "adj_factors": "adapt_adj_factors_batch",
                    "financial": "adapt_financial",
                    "news": "adapt_news",
                    "trade_calendar": "adapt_trade_calendar_batch",
                }

                method_name = domain_method_map.get(domain)
                if method_name and hasattr(adapter, method_name):
                    batch_method = getattr(adapter, method_name)
                    schemas = batch_method(raw_data)
                    return [s.to_db_doc() for s in schemas if s is not None]

                # 非批量的逐行方法
                row_method_map = {
                    "financial": "adapt_financial",
                    "news": "adapt_news",
                }
                row_method_name = row_method_map.get(domain)
                if row_method_name and hasattr(adapter, row_method_name):
                    row_method = getattr(adapter, row_method_name)
                    results = []
                    for _, row in raw_data.iterrows():
                        schema = row_method(row)
                        if schema is not None:
                            results.append(schema.to_db_doc())
                    return results if results else raw_data

                return raw_data

            # dict / list → 尝试逐项适配
            if isinstance(raw_data, list):
                results = []
                for item in raw_data:
                    if isinstance(item, dict):
                        schema = None
                        if domain == "news" and hasattr(adapter, "adapt_news"):
                            schema = adapter.adapt_news(item)
                        elif domain == "financial" and hasattr(adapter, "adapt_financial"):
                            schema = adapter.adapt_financial(item)
                        elif domain == "basic_info" and hasattr(adapter, "adapt_basic_info"):
                            schema = adapter.adapt_basic_info(item)
                        if schema is not None:
                            results.append(schema.to_db_doc())
                        else:
                            results.append(item)
                    else:
                        results.append(item)
                return results if results else raw_data

            if isinstance(raw_data, dict):
                if domain == "basic_info" and hasattr(adapter, "adapt_basic_info"):
                    schema = adapter.adapt_basic_info(raw_data)
                    if schema is not None:
                        return schema.to_db_doc()
                return raw_data

            return raw_data

        except Exception as e:
            logger.debug("Adapter 标准化失败，返回原始数据: %s", e)
            return raw_data

    @staticmethod
    def _classify_error(error: Exception) -> ErrorCategory:
        """将异常分类为 ErrorCategory"""
        msg = str(error).lower()

        if "429" in msg or "rate limit" in msg or "频繁" in msg:
            return ErrorCategory.RATE_LIMITED
        if "403" in msg or "forbidden" in msg or "token" in msg:
            return ErrorCategory.AUTH_FAILED
        if "timeout" in msg or "超时" in msg:
            return ErrorCategory.NETWORK_TIMEOUT
        if "connection" in msg or "连接" in msg:
            return ErrorCategory.CONNECTION_ERROR
        if "500" in msg or "502" in msg or "503" in msg or "server" in msg:
            return ErrorCategory.SERVER_ERROR
        if "empty" in msg or "空" in msg or "no data" in msg:
            return ErrorCategory.EMPTY_RESULT
        if "parse" in msg or "format" in msg or "格式" in msg:
            return ErrorCategory.DATA_INVALID

        return ErrorCategory.UNKNOWN

    # ── source_health 追踪 ──

    def _record_health_sample(
        self,
        source: str,
        domain: str,
        success: bool,
        latency_ms: int = 0,
        error: Optional[str] = None,
    ) -> None:
        """记录一次调用健康样本（进程内滑动窗口）"""
        key = (source, domain)
        if key not in self._health_samples:
            self._health_samples[key] = deque(maxlen=self._HEALTH_WINDOW_SIZE)

        self._health_samples[key].append({
            "success": success,
            "latency_ms": latency_ms,
            "error": error,
            "timestamp": time.monotonic(),
        })

        self._health_write_counter += 1
        if self._health_write_counter >= self._health_flush_interval:
            self._health_write_counter = 0
            # 触发异步写入（不阻塞当前请求）
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(self._flush_health_to_mongo())
            except RuntimeError:
                pass

    def get_source_health(self) -> List[Dict[str, Any]]:
        """获取所有数据源的健康统计（从滑动窗口计算）"""
        from app.data.schema.collections import get_collection_name
        from .circuit_breaker import CircuitState

        result = []
        now = time.monotonic()

        for (source, domain), samples in self._health_samples.items():
            if not samples:
                continue

            total = len(samples)
            successes = sum(1 for s in samples if s["success"])
            latencies = [s["latency_ms"] for s in samples if s["success"] and s["latency_ms"] > 0]

            # 计算连续失败数
            consecutive_failures = 0
            for s in reversed(samples):
                if not s["success"]:
                    consecutive_failures += 1
                else:
                    break

            circuit_state = self.circuit_breaker.get_state(source, domain)
            cb_info = self.circuit_breaker.get_all_states().get((source, domain), {})

            result.append({
                "source": source,
                "domain": domain,
                "circuit_state": circuit_state.value,
                "success_rate_1h": round(successes / total, 3) if total > 0 else 0,
                "avg_latency_1h": int(sum(latencies) / len(latencies)) if latencies else 0,
                "total_calls": total,
                "consecutive_failures": consecutive_failures,
                "open_count": cb_info.get("open_count", 0),
                "next_retry_at": cb_info.get("next_retry_at"),
            })

        return result

    async def _flush_health_to_mongo(self) -> None:
        """将 source_health 快照写入 MongoDB"""
        try:
            from app.core.database import get_database
            from app.data.schema.collections import get_collection_name
            from app.utils.time_utils import now_utc

            db = await get_database()
            collection = db[get_collection_name("CN", "source_health")]

            health_data = self.get_source_health()
            now_iso = now_utc().isoformat()

            for item in health_data:
                filter_doc = {"source": item["source"], "domain": item["domain"]}
                update_doc = {"$set": {**item, "updated_at": now_iso}}
                try:
                    await collection.update_one(filter_doc, update_doc, upsert=True)
                except Exception:
                    pass
        except Exception:
            logger.debug("source_health 写入 MongoDB 失败（非关键路径）")
