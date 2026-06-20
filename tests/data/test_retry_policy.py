"""重试策略测试 — 错误分类、退避时间、最大重试次数、执行流程。"""

import asyncio

import pytest

from app.data.processor.retry_policy import (
    BACKOFF_TIMES,
    MAX_RETRIES,
    NON_RETRYABLE_CODES,
    RETRYABLE_CODES,
    RetryPolicy,
    get_backoff,
    is_retryable,
)
from app.data.sources.base.error_codes import DataErrorCode
from app.data.sources.base.exceptions import (
    DataSourceError,
    RateLimitedError,
    TokenInvalidError,
)


# ── 错误分类 ──────────────────────────────────────────────


class TestIsRetryable:
    """可重试 vs 不可重试错误分类。"""

    def test_rate_limited_is_retryable(self):
        err = RateLimitedError("tushare", "daily_quotes")
        assert is_retryable(err) is True

    def test_network_timeout_is_retryable(self):
        err = DataSourceError(DataErrorCode.NETWORK_TIMEOUT, "tushare", "daily_quotes")
        assert is_retryable(err) is True

    def test_connection_error_is_retryable(self):
        err = DataSourceError(DataErrorCode.CONNECTION_ERROR, "tushare", "daily_quotes")
        assert is_retryable(err) is True

    def test_auth_failed_not_retryable(self):
        err = DataSourceError(DataErrorCode.AUTH_FAILED, "tushare", "daily_quotes")
        assert is_retryable(err) is False

    def test_token_invalid_not_retryable(self):
        err = TokenInvalidError("tushare", "daily_quotes")
        assert is_retryable(err) is False

    def test_insufficient_credits_not_retryable(self):
        err = DataSourceError(DataErrorCode.INSUFFICIENT_CREDITS, "tushare", "daily_quotes")
        assert is_retryable(err) is False

    def test_server_error_not_retryable(self):
        err = DataSourceError(DataErrorCode.SERVER_ERROR, "tushare", "daily_quotes")
        assert is_retryable(err) is False

    def test_data_invalid_not_retryable(self):
        err = DataSourceError(DataErrorCode.DATA_INVALID, "tushare", "daily_quotes")
        assert is_retryable(err) is False

    def test_empty_result_not_retryable(self):
        err = DataSourceError(DataErrorCode.EMPTY_RESULT, "tushare", "daily_quotes")
        assert is_retryable(err) is False

    def test_symbol_not_found_not_retryable(self):
        err = DataSourceError(DataErrorCode.SYMBOL_NOT_FOUND, "tushare", "daily_quotes")
        assert is_retryable(err) is False

    def test_not_supported_not_retryable(self):
        err = DataSourceError(DataErrorCode.NOT_SUPPORTED, "tushare", "daily_quotes")
        assert is_retryable(err) is False

    def test_generic_exception_not_retryable(self):
        assert is_retryable(ValueError("oops")) is False

    def test_generic_runtime_error_not_retryable(self):
        assert is_retryable(RuntimeError("boom")) is False

    def test_retryable_codes_cover_known_retryable(self):
        assert RETRYABLE_CODES == {
            DataErrorCode.RATE_LIMITED,
            DataErrorCode.NETWORK_TIMEOUT,
            DataErrorCode.CONNECTION_ERROR,
            # P1-1：服务暂时不可用（上游 5xx）也作为可重试错误
            DataErrorCode.SERVICE_UNAVAILABLE,
        }

    def test_non_retryable_codes_cover_all_others(self):
        assert DataErrorCode.AUTH_FAILED in NON_RETRYABLE_CODES
        assert DataErrorCode.TOKEN_INVALID in NON_RETRYABLE_CODES
        assert DataErrorCode.INSUFFICIENT_CREDITS in NON_RETRYABLE_CODES


# ── 退避时间 ──────────────────────────────────────────────


class TestGetBackoff:
    """退避时间计算。"""

    def test_rate_limited_first_attempt(self):
        err = RateLimitedError("tushare", "daily_quotes")
        assert get_backoff(err, 0) == 3

    def test_rate_limited_second_attempt(self):
        err = RateLimitedError("tushare", "daily_quotes")
        assert get_backoff(err, 1) == 10

    def test_rate_limited_attempt_beyond_list(self):
        err = RateLimitedError("tushare", "daily_quotes")
        assert get_backoff(err, 5) == 10  # 超出索引取最后一个

    def test_network_timeout_backoff(self):
        err = DataSourceError(DataErrorCode.NETWORK_TIMEOUT, "tushare", "daily_quotes")
        assert get_backoff(err, 0) == 5
        assert get_backoff(err, 1) == 15

    def test_connection_error_backoff(self):
        err = DataSourceError(DataErrorCode.CONNECTION_ERROR, "tushare", "daily_quotes")
        assert get_backoff(err, 0) == 2
        assert get_backoff(err, 1) == 5

    def test_non_retryable_code_default_backoff(self):
        err = DataSourceError(DataErrorCode.AUTH_FAILED, "tushare", "daily_quotes")
        assert get_backoff(err, 0) == 1
        assert get_backoff(err, 1) == 3

    def test_generic_exception_default_backoff(self):
        assert get_backoff(ValueError("x"), 0) == 1.0

    def test_backoff_times_structure(self):
        for code in RETRYABLE_CODES:
            assert code in BACKOFF_TIMES
            assert len(BACKOFF_TIMES[code]) >= 2


# ── 最大重试次数 ──────────────────────────────────────────


class TestMaxRetries:
    """最大重试次数配置。"""

    def test_default_max_retries(self):
        assert MAX_RETRIES == 2

    def test_policy_default_matches_constant(self):
        policy = RetryPolicy()
        assert policy.max_retries == MAX_RETRIES

    def test_policy_custom_max_retries(self):
        policy = RetryPolicy(max_retries=5)
        assert policy.max_retries == 5

    def test_policy_zero_retries(self):
        policy = RetryPolicy(max_retries=0)
        assert policy.max_retries == 0


# ── RetryPolicy 执行流程 ─────────────────────────────────


class TestRetryPolicyExecution:
    """RetryPolicy.execute_with_retry 执行流程。"""

    @pytest.mark.asyncio
    async def test_success_no_retry(self):
        """首次成功不重试。"""
        policy = RetryPolicy()
        call_count = 0

        async def succeed(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            return "ok"

        result = await policy.execute_with_retry(succeed)
        assert result == "ok"
        assert call_count == 1

    @pytest.mark.asyncio
    async def test_retryable_error_retried(self):
        """可重试错误会被重试直到成功。"""
        policy = RetryPolicy(max_retries=2)
        call_count = 0

        async def fail_then_succeed(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise RateLimitedError("tushare", "daily_quotes")
            return "recovered"

        result = await policy.execute_with_retry(fail_then_succeed)
        assert result == "recovered"
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_retryable_error_exhausted(self):
        """超过最大重试次数后抛出异常。"""
        policy = RetryPolicy(max_retries=1)

        async def always_fail(*args, **kwargs):
            raise RateLimitedError("tushare", "daily_quotes")

        with pytest.raises(RateLimitedError):
            await policy.execute_with_retry(always_fail)

    @pytest.mark.asyncio
    async def test_non_retryable_error_raised_immediately(self):
        """不可重试错误立即抛出。"""
        policy = RetryPolicy(max_retries=3)
        call_count = 0

        async def fail_auth(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            raise TokenInvalidError("tushare", "daily_quotes")

        with pytest.raises(TokenInvalidError):
            await policy.execute_with_retry(fail_auth)
        assert call_count == 1  # 只调用一次，不重试

    @pytest.mark.asyncio
    async def test_generic_error_raised_immediately(self):
        """非 DataSourceError 异常立即抛出。"""
        policy = RetryPolicy(max_retries=3)

        async def raise_value_error(*args, **kwargs):
            raise ValueError("bad input")

        with pytest.raises(ValueError):
            await policy.execute_with_retry(raise_value_error)

    @pytest.mark.asyncio
    async def test_args_and_kwargs_passed(self):
        """参数和关键字参数正确传递。"""
        policy = RetryPolicy()
        received = {}

        async def capture_args(a, b, key=None):
            received["a"] = a
            received["b"] = b
            received["key"] = key
            return "done"

        result = await policy.execute_with_retry(capture_args, 1, 2, key="val")
        assert result == "done"
        assert received == {"a": 1, "b": 2, "key": "val"}

    @pytest.mark.asyncio
    async def test_backoff_respected(self):
        """重试之间有退避等待（mock sleep 验证）。"""
        policy = RetryPolicy(max_retries=1)
        sleep_calls = []

        async def fail_once(*args, **kwargs):
            if not hasattr(fail_once, "called"):
                fail_once.called = True
                raise DataSourceError(DataErrorCode.NETWORK_TIMEOUT, "tushare", "daily_quotes")
            return "ok"

        import app.data.processor.retry_policy as rp_module

        original_sleep = asyncio.sleep

        async def mock_sleep(seconds):
            sleep_calls.append(seconds)
            await original_sleep(0)

        rp_module.asyncio.sleep = mock_sleep
        try:
            result = await policy.execute_with_retry(fail_once)
            assert result == "ok"
            assert len(sleep_calls) == 1
            assert sleep_calls[0] == 5  # NETWORK_TIMEOUT 第一次退避
        finally:
            rp_module.asyncio.sleep = original_sleep

    @pytest.mark.asyncio
    async def test_zero_retries_raises_on_first_failure(self):
        """max_retries=0 时不重试。"""
        policy = RetryPolicy(max_retries=0)

        async def fail(*args, **kwargs):
            raise RateLimitedError("tushare", "daily_quotes")

        with pytest.raises(RateLimitedError):
            await policy.execute_with_retry(fail)

    @pytest.mark.asyncio
    async def test_mixed_error_types_stops_on_non_retryable(self):
        """先可重试后不可重试，不可重试时立即停止。"""
        policy = RetryPolicy(max_retries=3)
        call_count = 0

        async def mixed_fail(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RateLimitedError("tushare", "daily_quotes")
            raise TokenInvalidError("tushare", "daily_quotes")

        with pytest.raises(TokenInvalidError):
            await policy.execute_with_retry(mixed_fail)
        assert call_count == 2
