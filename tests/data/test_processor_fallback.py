"""测试 FallbackRouter — 重试逻辑、降级记录。

设计原则：不使用 unittest.mock，使用真实的 CapabilityRegistry + PriorityConfig。
"""

import pytest

from app.data.processor.fallback_router import FallbackRouter, FetchResult
from app.data.core.registry.capability import CapabilityRegistry
from app.data.core.registry.priority import PriorityConfig
from app.data.schema.base.enums import SupportLevel


class TestFetchResult:
    def test_init(self):
        r = FetchResult()
        assert r.success is False
        assert r.records == []
        assert r.source is None
        assert r.error is None

    def test_with_data(self):
        r = FetchResult()
        r.success = True
        r.records = [{"symbol": "000001"}]
        r.source = "tushare"
        assert r.success is True
        assert len(r.records) == 1


class TestFallbackRouter:
    def test_init(self):
        registry = CapabilityRegistry()
        priority = PriorityConfig()
        router = FallbackRouter(registry, priority)
        assert router._circuit is not None
        assert router._rate_limiter is not None

    @pytest.mark.asyncio
    async def test_no_sources_for_unregistered_domain(self):
        """未注册的域应返回失败。"""
        registry = CapabilityRegistry()
        priority = PriorityConfig()
        router = FallbackRouter(registry, priority)

        result = await router.fetch("CN", "nonexistent_domain_xyz", "000001")
        assert result.success is False
        assert "无可用数据源" in result.error

    @pytest.mark.asyncio
    async def test_registered_sources_available(self):
        """注册了数据源的域应能查找到数据源。"""
        registry = CapabilityRegistry()
        registry.register("CN", "test_domain", "test_source", SupportLevel.FULL)
        priority = PriorityConfig()
        router = FallbackRouter(registry, priority)

        ordered = registry.get_ordered_sources("CN", "test_domain")
        assert "test_source" in ordered
