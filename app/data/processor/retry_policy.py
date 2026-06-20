"""重试策略 — 错误分类与退避。"""

import asyncio
import logging

from app.data.sources.base.error_codes import DataErrorCode
from app.data.sources.base.exceptions import DataSourceError

logger = logging.getLogger(__name__)

MAX_RETRIES = 2

RETRYABLE_CODES = {
    DataErrorCode.RATE_LIMITED,
    DataErrorCode.NETWORK_TIMEOUT,
    DataErrorCode.CONNECTION_ERROR,
    DataErrorCode.SERVICE_UNAVAILABLE,
}

NON_RETRYABLE_CODES = {
    DataErrorCode.AUTH_FAILED,
    DataErrorCode.TOKEN_INVALID,
    DataErrorCode.INSUFFICIENT_CREDITS,
    DataErrorCode.SERVER_ERROR,
    DataErrorCode.DATA_INVALID,
    DataErrorCode.EMPTY_RESULT,
    DataErrorCode.SYMBOL_NOT_FOUND,
    DataErrorCode.NOT_SUPPORTED,
}

# 错误类型 → 退避时间 (秒)
BACKOFF_TIMES = {
    DataErrorCode.RATE_LIMITED: [3, 10],
    DataErrorCode.NETWORK_TIMEOUT: [5, 15],
    DataErrorCode.CONNECTION_ERROR: [2, 5],
    # 服务暂时不可用：通常指上游 5xx，需要稍长退避以等待上游恢复
    DataErrorCode.SERVICE_UNAVAILABLE: [5, 15],
}


def is_retryable(error: Exception) -> bool:
    """判断错误是否可重试。"""
    if isinstance(error, DataSourceError):
        return error.code in RETRYABLE_CODES
    return False


def get_backoff(error: Exception, attempt: int) -> float:
    """获取退避等待时间。"""
    if isinstance(error, DataSourceError):
        times = BACKOFF_TIMES.get(error.code, [1, 3])
        idx = min(attempt, len(times) - 1)
        return times[idx]
    return 1.0


class RetryPolicy:
    """重试策略执行器。"""

    def __init__(self, max_retries: int = MAX_RETRIES):
        self.max_retries = max_retries

    async def execute_with_retry(self, func, *args, **kwargs):
        """执行函数，失败时按策略重试。"""
        last_error = None

        for attempt in range(self.max_retries + 1):
            try:
                result = await func(*args, **kwargs)
                return result
            except Exception as e:
                last_error = e
                if not is_retryable(e):
                    raise

                if attempt < self.max_retries:
                    backoff = get_backoff(e, attempt)
                    logger.debug(f"重试 {attempt + 1}/{self.max_retries}, 等待 {backoff}s: {e}")
                    await asyncio.sleep(backoff)
                else:
                    raise

        raise last_error
