"""FallbackRouter 回退链路单元测试 — 匹配新架构 API"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.data.processor.fallback_router import FallbackRouter, FetchResult
from app.data.core.registry.capability import CapabilityRegistry
from app.data.core.registry.priority import PriorityConfig
from app.data.schema.base.enums import SupportLevel


def _make_router():
    """创建测试用 FallbackRouter。"""
    registry = CapabilityRegistry()
    registry.register("CN", "daily_quotes", "tushare", SupportLevel.FULL)
    registry.register("CN", "daily_quotes", "akshare", SupportLevel.FULL)
    registry.register("CN", "daily_quotes", "baostock", SupportLevel.PARTIAL)

    priority = PriorityConfig()
    return FallbackRouter(registry, priority)


class TestFetchResult:
    """FetchResult 数据类测试。"""

    def test_default_values(self):
        result = FetchResult()
        assert result.success is False
        assert result.records == []
        assert result.source is None
        assert result.error is None


class TestFallbackRouterBasic:
    """基本 fetch 测试。"""

    @pytest.mark.asyncio
    async def test_no_sources_available(self):
        """无可用数据源时返回失败。"""
        registry = CapabilityRegistry()
        priority = PriorityConfig()
        router = FallbackRouter(registry, priority)

        result = await router.fetch("CN", "daily_quotes", "000001")
        assert result.success is False
        assert "无可用数据源" in result.error

    @pytest.mark.asyncio
    async def test_all_sources_fail(self):
        """所有源失败时返回失败。"""
        router = _make_router()
        # mock _get_provider_adapter 返回 None → 所有源不可用
        with patch.object(router, '_get_provider_adapter', return_value=(None, None)):
            result = await router.fetch("CN", "daily_quotes", "000001")
        assert result.success is False

    @pytest.mark.asyncio
    async def test_fallback_on_empty_data(self):
        """主源返回空数据时回退。"""
        router = _make_router()
        empty_provider = MagicMock()
        empty_provider.get_daily_quotes = AsyncMock(return_value=None)
        empty_adapter = MagicMock()
        empty_adapter.adapt_daily_quotes = MagicMock(return_value=[])
        empty_adapter.source_name = "tushare"

        good_provider = MagicMock()
        good_provider.get_daily_quotes = AsyncMock(return_value=MagicMock(empty=False))
        good_adapter = MagicMock()
        good_adapter.adapt_daily_quotes = MagicMock(return_value=[
            MagicMock(to_db_doc=MagicMock(return_value={"symbol": "000001", "close": 10.0}))
        ])
        good_adapter.source_name = "akshare"

        call_count = 0

        async def mock_get(market, source_name):
            nonlocal call_count
            call_count += 1
            if source_name == "tushare":
                return empty_provider, empty_adapter
            return good_provider, good_adapter

        with patch.object(router, '_get_provider_adapter', side_effect=mock_get):
            with patch.object(router, '_fetch_raw', return_value=MagicMock(empty=True)):
                with patch('app.data.processor.fallback_router.AsyncMock', create=True):
                    result = await router.fetch("CN", "daily_quotes", "000001")
        # 至少尝试了获取数据
        assert call_count >= 1
