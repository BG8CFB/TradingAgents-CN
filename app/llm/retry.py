"""
API 重试（参考 claude-code services/api/withRetry.ts）

- 上限 10 次，指数退避（基数 500ms）
- 429/限流连续 3 次 → 抛 FallbackTriggeredError（调用方可切换备选模型重试）
- 401/鉴权失败不重试（直接 AuthError）
- 网络类错误（连接重置等）可重试
"""

import asyncio
import logging
from typing import Awaitable, Callable, TypeVar

from .core.errors import AuthError, LLMError, RateLimitError

logger = logging.getLogger("app.llm.retry")

DEFAULT_MAX_RETRIES = 10  # 参考 claude-code DEFAULT_MAX_RETRIES
BASE_DELAY_MS = 500  # 指数退避基数
RATE_LIMIT_FALLBACK_THRESHOLD = 3  # 连续 3 次 429/限流 → 触发 fallback
MAX_DELAY_MS = 60_000

T = TypeVar("T")


class FallbackTriggeredError(LLMError):
    """连续限流达到阈值，调用方应切换 fallback 模型重试整个请求"""

    def __init__(self, message: str = "连续限流达到阈值，触发 fallback"):
        super().__init__(message)


def _delay_ms(attempt: int) -> int:
    return min(BASE_DELAY_MS * (2**attempt), MAX_DELAY_MS)


def _should_retry(exc: Exception) -> bool:
    if isinstance(exc, AuthError):
        return False  # 鉴权失败重试无意义
    if isinstance(exc, (RateLimitError, TimeoutError, ConnectionError, LLMError)):
        return True
    return False


async def with_retry(
    fn: Callable[[], Awaitable[T]],
    *,
    max_retries: int = DEFAULT_MAX_RETRIES,
    on_fallback_trigger: Callable[[], None] = lambda: None,
) -> T:
    """带重试执行 API 调用。限流连续达到阈值抛 FallbackTriggeredError。"""
    rate_limit_streak = 0
    attempt = 0
    while True:
        try:
            return await fn()
        except Exception as e:
            if not _should_retry(e):
                raise
            if isinstance(e, RateLimitError):
                rate_limit_streak += 1
                if rate_limit_streak >= RATE_LIMIT_FALLBACK_THRESHOLD:
                    on_fallback_trigger()
                    raise FallbackTriggeredError(f"连续 {rate_limit_streak} 次限流: {e}") from e
            else:
                rate_limit_streak = 0
            if attempt >= max_retries:
                raise
            delay = _delay_ms(attempt)
            logger.warning(
                f"⚠️ [retry] 第 {attempt + 1}/{max_retries} 次重试（{type(e).__name__}），{delay}ms 后重试: {e}"
            )
            await asyncio.sleep(delay / 1000)
            attempt += 1
