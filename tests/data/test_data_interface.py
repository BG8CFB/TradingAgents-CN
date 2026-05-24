"""测试 DataInterface — 数据平台统一门面。

覆盖范围：
- 单例模式（get_instance / reset_instance）
- read() 数据读取与新鲜度
- refresh() 按需刷新委托
- trigger_sync() 手动触发同步（使用 SimulatedMongoDB）
- get_sync_status() 同步状态查询
- get_sync_events() 同步事件查询
- get_source_health() 数据源健康查询
- get_config() / update_config() 配置管理

设计原则：不使用 unittest.mock，所有依赖使用真实构造。
对于 MongoDB 依赖，使用 SimulatedMongoDB 通过 inject_sim_db 注入。
"""

import pytest

from app.data.core.interface import DataInterface
from app.data.core.result import RefreshResult, DomainRefreshResult
from app.data.schema.base.enums import RefreshStatus


# ---------------------------------------------------------------------------
# 单例模式测试
# ---------------------------------------------------------------------------
class TestDataInterfaceSingleton:
    """测试 DataInterface 单例行为。"""

    def setup_method(self):
        DataInterface.reset_instance()

    def teardown_method(self):
        DataInterface.reset_instance()

    def test_get_instance_creates_singleton(self):
        instance = DataInterface.get_instance()
        assert instance is not None
        assert isinstance(instance, DataInterface)

    def test_get_instance_returns_same_object(self):
        a = DataInterface.get_instance()
        b = DataInterface.get_instance()
        assert a is b

    def test_reset_instance_clears_singleton(self):
        a = DataInterface.get_instance()
        DataInterface.reset_instance()
        b = DataInterface.get_instance()
        assert a is not b

    def test_constructor_creates_real_components(self):
        di = DataInterface()
        assert di.reader is not None
        assert di._registry is not None
        assert di._priority is not None
        assert di.refresh_service is not None


# ---------------------------------------------------------------------------
# 数据读取测试
# ---------------------------------------------------------------------------
class TestDataInterfaceRead:
    """测试 DataInterface.read() 方法。"""

    def setup_method(self):
        DataInterface.reset_instance()

    def teardown_method(self):
        DataInterface.reset_instance()

    @pytest.mark.asyncio
    async def test_read_returns_expected_structure(self, inject_sim_db):
        di = DataInterface()
        result = await di.read("CN", "daily_quotes", symbol="000001",
                               start_date="2024-01-01", end_date="2024-12-31")

        assert "data" in result
        assert "freshness" in result
        assert result["market"] == "CN"
        assert result["symbol"] == "000001"
        assert result["domain"] == "daily_quotes"

    @pytest.mark.asyncio
    async def test_read_without_symbol(self, inject_sim_db):
        di = DataInterface()
        result = await di.read("CN", "basic_info")
        assert result["market"] == "CN"
        assert result["symbol"] is None
        assert result["domain"] == "basic_info"

    @pytest.mark.asyncio
    async def test_read_hk_market(self, inject_sim_db):
        di = DataInterface()
        result = await di.read("HK", "news", symbol="00700")
        assert result["market"] == "HK"
        assert result["symbol"] == "00700"


# ---------------------------------------------------------------------------
# 刷新委托测试
# ---------------------------------------------------------------------------
class TestDataInterfaceRefresh:
    """测试 DataInterface.refresh() 委托给 DataRefreshService。"""

    def setup_method(self):
        DataInterface.reset_instance()

    def teardown_method(self):
        DataInterface.reset_instance()

    @pytest.mark.asyncio
    async def test_refresh_returns_refresh_result(self):
        di = DataInterface()
        result = await di.refresh("CN", "000001", domains=["daily_quotes"], force=True, timeout=60)
        assert isinstance(result, RefreshResult)
        assert result.symbol == "000001"
        assert result.market == "CN"


# ---------------------------------------------------------------------------
# 同步管理测试 — 使用 SimulatedMongoDB
# ---------------------------------------------------------------------------
class TestDataInterfaceSync:
    """测试同步相关方法。通过 inject_sim_db 使用内存 MongoDB。"""

    def setup_method(self):
        DataInterface.reset_instance()

    def teardown_method(self):
        DataInterface.reset_instance()

    @pytest.mark.asyncio
    async def test_trigger_sync_returns_task_id(self, inject_sim_db):
        di = DataInterface()
        task_id = await di.trigger_sync("CN", "daily_quotes")

        assert task_id.startswith("sync_CN_daily_quotes_")

    @pytest.mark.asyncio
    async def test_trigger_sync_writes_event(self, inject_sim_db):
        di = DataInterface()
        await di.trigger_sync("CN", "daily_quotes")

        events_coll = inject_sim_db["sync_events"]
        events = await events_coll.find({}).to_list()
        assert len(events) >= 1
        event = events[-1]
        assert event["market"] == "CN"
        assert event["domain"] == "daily_quotes"
        assert event["event_type"] == "SYNC_START"

    @pytest.mark.asyncio
    async def test_get_sync_status(self, inject_sim_db):
        di = DataInterface()
        await di.trigger_sync("CN", "daily_quotes")

        status = await di.get_sync_status("CN", "daily_quotes")
        assert isinstance(status, list)

    @pytest.mark.asyncio
    async def test_get_sync_events(self, inject_sim_db):
        di = DataInterface()
        await di.trigger_sync("CN", "daily_quotes")

        result = await di.get_sync_events("CN", limit=10)
        assert isinstance(result, list)
        assert len(result) >= 1

    @pytest.mark.asyncio
    async def test_get_sync_events_with_domain_filter(self, inject_sim_db):
        di = DataInterface()
        await di.trigger_sync("CN", "daily_quotes")
        await di.trigger_sync("CN", "basic_info")

        result = await di.get_sync_events("CN", domain="daily_quotes", limit=10)
        assert all(e.get("domain") == "daily_quotes" for e in result)


# ---------------------------------------------------------------------------
# 数据源管理测试
# ---------------------------------------------------------------------------
class TestDataInterfaceSourceManagement:
    """测试数据源健康和配置管理。"""

    def setup_method(self):
        DataInterface.reset_instance()

    def teardown_method(self):
        DataInterface.reset_instance()

    @pytest.mark.asyncio
    async def test_get_source_health(self, inject_sim_db):
        di = DataInterface()
        result = await di.get_source_health("CN")
        assert isinstance(result, list)

    @pytest.mark.asyncio
    async def test_get_config(self, inject_sim_db):
        di = DataInterface()
        result = await di.get_config("CN", "daily_quotes")
        assert result is None or isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_update_config_success(self, inject_sim_db):
        di = DataInterface()
        result = await di.update_config("CN", "daily_quotes", ["tushare", "akshare"], "admin")
        assert result is True

    @pytest.mark.asyncio
    async def test_update_and_read_config_roundtrip(self, inject_sim_db):
        di = DataInterface()
        await di.update_config("CN", "daily_quotes", ["tushare", "akshare"], "admin")
        config = await di.get_config("CN", "daily_quotes")
        assert config is not None
        stored_value = config.get("value", {})
        assert stored_value.get("sources") == ["tushare", "akshare"]

    def test_get_capability_registry(self):
        di = DataInterface()
        registry = di.get_capability_registry()
        assert registry is not None
        assert registry is di._registry
