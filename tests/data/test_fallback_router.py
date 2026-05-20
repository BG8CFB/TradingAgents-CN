"""FallbackRouter 回退链路单元测试"""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.data.processor.fallback_router import FallbackRouter, FetchResult, ErrorCategory


class MockProvider:
    """模拟 Provider"""

    def __init__(self, data=None, should_raise=None):
        self._data = data
        self._should_raise = should_raise

    async def get_daily_quotes(self, symbol, start_date, end_date):
        if self._should_raise:
            raise self._should_raise
        return self._data

    async def get_stock_basic_info(self, symbol):
        if self._should_raise:
            raise self._should_raise
        return self._data


class MockAdapter:
    """模拟 Adapter — 返回标准化 dict 列表"""

    def __init__(self, source_name="mock"):
        self.source_name = source_name

    def adapt_daily_quote_batch(self, df):
        import pandas as pd
        if isinstance(df, pd.DataFrame):
            return []
        return []

    def adapt_basic_info(self, row):
        return None


@pytest.fixture
def router():
    return FallbackRouter(max_retries=1)


class TestBasicFetch:
    """基本 fetch 测试"""

    @pytest.mark.asyncio
    async def test_success_first_source(self, router):
        mock_data = [{"symbol": "000001", "close": 10.0}]
        provider = MockProvider(data=mock_data)

        result = await router.fetch(
            "daily_quotes",
            symbol="000001",
            providers={"tushare": provider},
        )

        assert result.success
        assert result.source == "tushare"
        assert result.data is not None

    @pytest.mark.asyncio
    async def test_no_providers(self, router):
        result = await router.fetch("daily_quotes", symbol="000001", providers={})

        assert not result.success
        assert "无可用 Provider" in result.error or "不可用" in result.error

    @pytest.mark.asyncio
    async def test_fallback_on_failure(self, router):
        """主源失败时回退到备源"""
        failing_provider = MockProvider(should_raise=Exception("API Error"))
        good_data = [{"symbol": "000001", "close": 10.0}]
        good_provider = MockProvider(data=good_data)

        result = await router.fetch(
            "daily_quotes",
            symbol="000001",
            providers={
                "tushare": failing_provider,
                "akshare": good_provider,
            },
        )

        assert result.success
        assert result.source == "akshare"
        assert result.fallback_from == "tushare"

    @pytest.mark.asyncio
    async def test_all_sources_fail(self, router):
        p1 = MockProvider(should_raise=Exception("Error 1"))
        p2 = MockProvider(should_raise=Exception("Error 2"))

        result = await router.fetch(
            "daily_quotes",
            symbol="000001",
            providers={"tushare": p1, "akshare": p2},
        )

        assert not result.success


class TestAdapterIntegration:
    """Adapter 标准化集成测试"""

    @pytest.mark.asyncio
    async def test_adapter_called_for_success(self, router):
        mock_data = [{"ts_code": "000001.SZ", "close": 10.0}]
        provider = MockProvider(data=mock_data)
        adapter = MockAdapter()

        result = await router.fetch(
            "daily_quotes",
            symbol="000001",
            providers={"tushare": provider},
            adapters={"tushare": adapter},
        )

        assert result.success


class TestErrorClassification:
    """错误分类测试"""

    def test_rate_limited(self, router):
        e = Exception("HTTP 429 rate limited")
        cat = router._classify_error(e)
        assert cat == ErrorCategory.RATE_LIMITED

    def test_auth_failed(self, router):
        e = Exception("HTTP 403 forbidden token invalid")
        cat = router._classify_error(e)
        assert cat == ErrorCategory.AUTH_FAILED

    def test_timeout(self, router):
        e = Exception("Request timeout after 30s")
        cat = router._classify_error(e)
        assert cat == ErrorCategory.NETWORK_TIMEOUT

    def test_server_error(self, router):
        e = Exception("HTTP 500 internal server error")
        cat = router._classify_error(e)
        assert cat == ErrorCategory.SERVER_ERROR

    def test_unknown(self, router):
        e = Exception("Something unexpected")
        cat = router._classify_error(e)
        assert cat == ErrorCategory.UNKNOWN
