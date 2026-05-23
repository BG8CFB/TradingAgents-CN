"""CN 域同步模块和调度器测试。

设计原则：不使用 unittest.mock。router 依赖使用内联最小实现。
MongoDB 写入使用 SimulatedMongoDB 通过 inject_sim_db 注入。
"""

import pytest

from app.data.processor.fallback_router import FetchResult


def _make_fetch_result(**kwargs):
    """辅助：构造 FetchResult（构造函数无参，通过属性赋值）。"""
    r = FetchResult()
    for k, v in kwargs.items():
        setattr(r, k, v)
    return r


class TestDomainSyncResult:
    """测试 DomainSyncResult 数据类。"""

    def test_to_dict(self):
        from app.worker.cn.domain_sync.base_domain_sync import DomainSyncResult
        r = DomainSyncResult(
            domain="daily_quotes", success=True,
            source="tushare", records_synced=100,
            duration_ms=500,
        )
        d = r.to_dict()
        assert d["domain"] == "daily_quotes"
        assert d["success"] is True
        assert d["records_synced"] == 100


class TestBasicInfoSync:
    """测试 BasicInfoSync。"""

    @pytest.mark.asyncio
    async def test_sync_success(self, inject_sim_db):
        from app.worker.cn.domain_sync.basic_info_sync import BasicInfoSync
        from app.data.processor.fallback_router import FallbackRouter
        from app.data.core.registry.capability import CapabilityRegistry
        from app.data.core.registry.priority import PriorityConfig

        registry = CapabilityRegistry()
        priority = PriorityConfig()
        router = FallbackRouter(registry, priority)

        sync = BasicInfoSync(router=router)
        result = await sync.sync()

        assert result is not None
        assert result.domain == "basic_info"

    @pytest.mark.asyncio
    async def test_sync_returns_result_structure(self):
        from app.worker.cn.domain_sync.basic_info_sync import BasicInfoSync
        from app.data.processor.fallback_router import FallbackRouter
        from app.data.core.registry.capability import CapabilityRegistry
        from app.data.core.registry.priority import PriorityConfig

        registry = CapabilityRegistry()
        priority = PriorityConfig()
        router = FallbackRouter(registry, priority)

        sync = BasicInfoSync(router=router)
        result = await sync.sync()

        assert hasattr(result, "success")
        assert hasattr(result, "domain")
        assert hasattr(result, "source")


class TestDailyQuotesSync:
    """测试 DailyQuotesSync。"""

    @pytest.mark.asyncio
    async def test_requires_symbol(self):
        from app.worker.cn.domain_sync.daily_quotes_sync import DailyQuotesSync
        from app.data.processor.fallback_router import FallbackRouter
        from app.data.core.registry.capability import CapabilityRegistry
        from app.data.core.registry.priority import PriorityConfig

        registry = CapabilityRegistry()
        priority = PriorityConfig()
        router = FallbackRouter(registry, priority)

        sync = DailyQuotesSync(router=router)
        result = await sync.sync(symbol=None)

        assert not result.success
        assert "symbol" in result.error


class TestSchedulerSetup:
    """测试调度器辅助函数。"""

    def test_get_scheduler_engine_none_by_default(self):
        from app.worker.scheduler_setup import get_scheduler_engine
        engine = get_scheduler_engine()
        assert engine is None
