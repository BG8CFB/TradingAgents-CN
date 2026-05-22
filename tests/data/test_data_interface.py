"""测试 DataInterface — 数据平台统一门面。

覆盖范围：
- 单例模式（get_instance / reset_instance）
- read() 数据读取与新鲜度
- refresh() 按需刷新委托
- trigger_sync() 手动触发同步
- get_sync_status() 同步状态查询
- get_sync_events() 同步事件查询
- get_source_health() 数据源健康查询
- get_config() / update_config() 配置管理
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

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

    @patch("app.data.core.interface.Reader")
    @patch("app.data.core.interface.CapabilityRegistry")
    @patch("app.data.core.interface.PriorityConfig")
    @patch("app.data.core.interface.DataRefreshService")
    def test_get_instance_creates_singleton(self, mock_refresh, mock_priority, mock_cap, mock_reader):
        instance = DataInterface.get_instance()
        assert instance is not None
        assert isinstance(instance, DataInterface)

    @patch("app.data.core.interface.Reader")
    @patch("app.data.core.interface.CapabilityRegistry")
    @patch("app.data.core.interface.PriorityConfig")
    @patch("app.data.core.interface.DataRefreshService")
    def test_get_instance_returns_same_object(self, mock_refresh, mock_priority, mock_cap, mock_reader):
        a = DataInterface.get_instance()
        b = DataInterface.get_instance()
        assert a is b

    @patch("app.data.core.interface.Reader")
    @patch("app.data.core.interface.CapabilityRegistry")
    @patch("app.data.core.interface.PriorityConfig")
    @patch("app.data.core.interface.DataRefreshService")
    def test_reset_instance_clears_singleton(self, mock_refresh, mock_priority, mock_cap, mock_reader):
        a = DataInterface.get_instance()
        DataInterface.reset_instance()
        b = DataInterface.get_instance()
        assert a is not b


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
    @patch("app.data.core.interface.Reader")
    @patch("app.data.core.interface.CapabilityRegistry")
    @patch("app.data.core.interface.PriorityConfig")
    @patch("app.data.core.interface.DataRefreshService")
    async def test_read_returns_expected_structure(self, mock_refresh_cls, mock_priority_cls, mock_cap_cls, mock_reader_cls):
        mock_reader = MagicMock()
        mock_reader.get_data = AsyncMock(return_value=(
            [{"symbol": "000001", "close": 10.5}],
            "fresh",
        ))
        mock_reader_cls.return_value = mock_reader

        di = DataInterface()
        result = await di.read("CN", "000001", "daily_quotes", start_date="2024-01-01", end_date="2024-12-31")

        assert result["data"] == [{"symbol": "000001", "close": 10.5}]
        assert result["freshness"] == "fresh"
        assert result["market"] == "CN"
        assert result["symbol"] == "000001"
        assert result["domain"] == "daily_quotes"
        mock_reader.get_data.assert_awaited_once_with(
            "CN", "000001", "daily_quotes", start_date="2024-01-01", end_date="2024-12-31"
        )

    @pytest.mark.asyncio
    @patch("app.data.core.interface.Reader")
    @patch("app.data.core.interface.CapabilityRegistry")
    @patch("app.data.core.interface.PriorityConfig")
    @patch("app.data.core.interface.DataRefreshService")
    async def test_read_returns_none_data_when_empty(self, mock_refresh_cls, mock_priority_cls, mock_cap_cls, mock_reader_cls):
        mock_reader = MagicMock()
        mock_reader.get_data = AsyncMock(return_value=(None, "unknown"))
        mock_reader_cls.return_value = mock_reader

        di = DataInterface()
        result = await di.read("HK", "00700", "news")

        assert result["data"] is None
        assert result["freshness"] == "unknown"
        assert result["market"] == "HK"


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
    @patch("app.data.core.interface.Reader")
    @patch("app.data.core.interface.CapabilityRegistry")
    @patch("app.data.core.interface.PriorityConfig")
    @patch("app.data.core.interface.DataRefreshService")
    async def test_refresh_delegates_to_service(self, mock_refresh_cls, mock_priority_cls, mock_cap_cls, mock_reader_cls):
        mock_service = MagicMock()
        expected_result = RefreshResult(symbol="000001", market="CN", status=RefreshStatus.REFRESHED)
        mock_service.refresh = AsyncMock(return_value=expected_result)
        mock_refresh_cls.return_value = mock_service

        di = DataInterface()
        result = await di.refresh("CN", "000001", domains=["daily_quotes"], force=True, timeout=60)

        assert result.status == RefreshStatus.REFRESHED
        mock_service.refresh.assert_awaited_once_with("CN", "000001", ["daily_quotes"], True, 60)


# ---------------------------------------------------------------------------
# 同步管理测试
# ---------------------------------------------------------------------------
class TestDataInterfaceSync:
    """测试同步相关方法。MetadataRepo 通过延迟导入使用。"""

    def setup_method(self):
        DataInterface.reset_instance()

    def teardown_method(self):
        DataInterface.reset_instance()

    @pytest.mark.asyncio
    @patch("app.data.core.interface.Reader")
    @patch("app.data.core.interface.CapabilityRegistry")
    @patch("app.data.core.interface.PriorityConfig")
    @patch("app.data.core.interface.DataRefreshService")
    async def test_trigger_sync_returns_task_id(self, mock_refresh_cls, mock_priority_cls, mock_cap_cls, mock_reader_cls):
        mock_repo = MagicMock()
        mock_repo.insert_event = AsyncMock(return_value=None)
        with patch("app.data.storage.mongo.repositories.metadata_repo.MetadataRepo", return_value=mock_repo):
            di = DataInterface()
            task_id = await di.trigger_sync("CN", "daily_quotes")

        assert task_id.startswith("sync_CN_daily_quotes_")
        mock_repo.insert_event.assert_awaited_once()
        event_arg = mock_repo.insert_event.call_args[0][0]
        assert event_arg["market"] == "CN"
        assert event_arg["domain"] == "daily_quotes"
        assert event_arg["event_type"] == "SYNC_START"

    @pytest.mark.asyncio
    @patch("app.data.core.interface.Reader")
    @patch("app.data.core.interface.CapabilityRegistry")
    @patch("app.data.core.interface.PriorityConfig")
    @patch("app.data.core.interface.DataRefreshService")
    async def test_get_sync_status(self, mock_refresh_cls, mock_priority_cls, mock_cap_cls, mock_reader_cls):
        mock_repo = MagicMock()
        mock_repo.get_checkpoint = AsyncMock(return_value={"last_sync_date": "2024-12-31"})
        mock_repo.get_events = AsyncMock(return_value=[{"event_type": "SYNC_SUCCESS"}])
        with patch("app.data.storage.mongo.repositories.metadata_repo.MetadataRepo", return_value=mock_repo):
            di = DataInterface()
            status = await di.get_sync_status("CN", "daily_quotes")

        assert status["checkpoint"] == {"last_sync_date": "2024-12-31"}
        assert status["recent_events"] == [{"event_type": "SYNC_SUCCESS"}]

    @pytest.mark.asyncio
    @patch("app.data.core.interface.Reader")
    @patch("app.data.core.interface.CapabilityRegistry")
    @patch("app.data.core.interface.PriorityConfig")
    @patch("app.data.core.interface.DataRefreshService")
    async def test_get_sync_events(self, mock_refresh_cls, mock_priority_cls, mock_cap_cls, mock_reader_cls):
        mock_repo = MagicMock()
        events = [{"event_type": "SYNC_START"}, {"event_type": "SYNC_SUCCESS"}]
        mock_repo.get_events = AsyncMock(return_value=events)
        with patch("app.data.storage.mongo.repositories.metadata_repo.MetadataRepo", return_value=mock_repo):
            di = DataInterface()
            result = await di.get_sync_events("CN", limit=10)

        assert result == events
        mock_repo.get_events.assert_awaited_once_with("CN", None, 10)


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
    @patch("app.data.core.interface.Reader")
    @patch("app.data.core.interface.CapabilityRegistry")
    @patch("app.data.core.interface.PriorityConfig")
    @patch("app.data.core.interface.DataRefreshService")
    async def test_get_source_health(self, mock_refresh_cls, mock_priority_cls, mock_cap_cls, mock_reader_cls):
        mock_repo = MagicMock()
        health_data = [{"source": "tushare", "success_rate": 0.98}]
        mock_repo.get_all_health = AsyncMock(return_value=health_data)
        with patch("app.data.storage.mongo.repositories.metadata_repo.MetadataRepo", return_value=mock_repo):
            di = DataInterface()
            result = await di.get_source_health("CN")

        assert result == health_data

    @pytest.mark.asyncio
    @patch("app.data.core.interface.Reader")
    @patch("app.data.core.interface.CapabilityRegistry")
    @patch("app.data.core.interface.PriorityConfig")
    @patch("app.data.core.interface.DataRefreshService")
    async def test_get_config(self, mock_refresh_cls, mock_priority_cls, mock_cap_cls, mock_reader_cls):
        mock_repo = MagicMock()
        config_data = {"sources": ["tushare", "akshare"]}
        mock_repo.get_config = AsyncMock(return_value=config_data)
        with patch("app.data.storage.mongo.repositories.metadata_repo.MetadataRepo", return_value=mock_repo):
            di = DataInterface()
            result = await di.get_config("CN", "daily_quotes")

        assert result == config_data
        mock_repo.get_config.assert_awaited_once_with("data_source_priority", "CN", "daily_quotes")

    @pytest.mark.asyncio
    @patch("app.data.core.interface.Reader")
    @patch("app.data.core.interface.CapabilityRegistry")
    @patch("app.data.core.interface.PriorityConfig")
    @patch("app.data.core.interface.DataRefreshService")
    async def test_update_config_success(self, mock_refresh_cls, mock_priority_cls, mock_cap_cls, mock_reader_cls):
        mock_repo = MagicMock()
        mock_repo.upsert_config = AsyncMock(return_value=None)

        mock_priority = MagicMock()
        mock_priority.invalidate_cache = MagicMock()

        with patch("app.data.storage.mongo.repositories.metadata_repo.MetadataRepo", return_value=mock_repo):
            di = DataInterface()
            di._priority = mock_priority
            result = await di.update_config("CN", "daily_quotes", ["tushare", "akshare"], "admin")

        assert result is True
        mock_repo.upsert_config.assert_awaited_once_with(
            "data_source_priority", "CN", "daily_quotes",
            {"sources": ["tushare", "akshare"]}, "admin"
        )
        mock_priority.invalidate_cache.assert_called_once_with("CN", "daily_quotes")

    def test_get_capability_registry(self):
        with patch("app.data.core.interface.Reader"), \
             patch("app.data.core.interface.CapabilityRegistry") as mock_cap_cls, \
             patch("app.data.core.interface.PriorityConfig"), \
             patch("app.data.core.interface.DataRefreshService"):
            mock_registry = MagicMock()
            mock_cap_cls.return_value = mock_registry
            di = DataInterface()
            registry = di.get_capability_registry()
            assert registry is mock_registry
