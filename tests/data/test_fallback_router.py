"""FallbackRouter 回退链路单元测试 — 匹配新架构 API。

设计原则：不使用 unittest.mock，使用真实的 CapabilityRegistry + PriorityConfig。
Provider/Adapter 层使用最小化内联实现替代 MagicMock。
"""

import pytest

from app.data.processor.fallback_router import FallbackRouter, FetchResult
from app.data.core.registry.capability import CapabilityRegistry
from app.data.core.registry.priority import PriorityConfig
from app.data.schema.base.enums import SupportLevel


def _make_router_with_sources():
    """创建注册了多个数据源的 FallbackRouter。"""
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

        result = await router.fetch("CN", "nonexistent_domain_xyz", "000001")
        assert result.success is False
        assert "无可用数据源" in result.error

    @pytest.mark.asyncio
    async def test_fallback_router_init(self):
        """验证 FallbackRouter 正确初始化。"""
        router = _make_router_with_sources()
        assert router._circuit is not None
        assert router._rate_limiter is not None

    @pytest.mark.asyncio
    async def test_fetch_returns_result_structure(self):
        """fetch 返回结果包含预期字段。"""
        router = _make_router_with_sources()
        result = await router.fetch("CN", "daily_quotes", "000001")
        assert hasattr(result, "success")
        assert hasattr(result, "records")
        assert hasattr(result, "source")
        assert hasattr(result, "error")
