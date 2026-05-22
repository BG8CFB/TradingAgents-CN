"""检查点管理器测试 — CRUD 操作。"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.data.scheduler.checkpoint import CheckpointManager


@pytest.fixture
def mock_repo():
    """创建 MetadataRepo mock。"""
    with patch("app.data.scheduler.checkpoint.MetadataRepo") as MockRepo:
        repo_instance = MagicMock()
        MockRepo.return_value = repo_instance
        yield repo_instance


class TestGetCheckpoint:
    """获取检查点。"""

    @pytest.mark.asyncio
    async def test_returns_last_sync_date(self, mock_repo):
        mock_repo.get_checkpoint = AsyncMock(return_value={
            "last_sync_date": "2024-06-15",
            "record_count": 100,
        })
        mgr = CheckpointManager()
        result = await mgr.get_checkpoint("CN", "daily_quotes", "tushare")
        assert result == "2024-06-15"
        mock_repo.get_checkpoint.assert_called_once_with("CN", "daily_quotes", "tushare")

    @pytest.mark.asyncio
    async def test_returns_none_when_no_checkpoint(self, mock_repo):
        mock_repo.get_checkpoint = AsyncMock(return_value=None)
        mgr = CheckpointManager()
        result = await mgr.get_checkpoint("CN", "daily_quotes", "tushare")
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_for_empty_result(self, mock_repo):
        mock_repo.get_checkpoint = AsyncMock(return_value={})
        mgr = CheckpointManager()
        result = await mgr.get_checkpoint("HK", "daily_quotes", "tushare_hk")
        assert result is None

    @pytest.mark.asyncio
    async def test_passes_correct_market_domain_source(self, mock_repo):
        mock_repo.get_checkpoint = AsyncMock(return_value={"last_sync_date": "2024-01-01"})
        mgr = CheckpointManager()
        await mgr.get_checkpoint("US", "basic_info", "yfinance")
        mock_repo.get_checkpoint.assert_called_once_with("US", "basic_info", "yfinance")


class TestUpdateCheckpoint:
    """更新检查点。"""

    @pytest.mark.asyncio
    async def test_update_passes_all_params(self, mock_repo):
        mock_repo.update_checkpoint = AsyncMock()
        mgr = CheckpointManager()
        await mgr.update_checkpoint("CN", "daily_quotes", "tushare", "2024-06-15", 500)
        mock_repo.update_checkpoint.assert_called_once_with(
            "CN", "daily_quotes", "tushare", "2024-06-15", 500
        )

    @pytest.mark.asyncio
    async def test_update_with_different_market(self, mock_repo):
        mock_repo.update_checkpoint = AsyncMock()
        mgr = CheckpointManager()
        await mgr.update_checkpoint("HK", "basic_info", "akshare_hk", "2024-01-01", 50)
        mock_repo.update_checkpoint.assert_called_once_with(
            "HK", "basic_info", "akshare_hk", "2024-01-01", 50
        )

    @pytest.mark.asyncio
    async def test_update_with_zero_count(self, mock_repo):
        mock_repo.update_checkpoint = AsyncMock()
        mgr = CheckpointManager()
        await mgr.update_checkpoint("US", "daily_quotes", "yfinance", "2024-03-01", 0)
        mock_repo.update_checkpoint.assert_called_once()


class TestResetCheckpoint:
    """重置检查点（强制全量同步）。"""

    @pytest.mark.asyncio
    async def test_reset_sets_epoch_date(self, mock_repo):
        mock_repo.update_checkpoint = AsyncMock()
        mgr = CheckpointManager()
        await mgr.reset_checkpoint("CN", "daily_quotes", "tushare")
        mock_repo.update_checkpoint.assert_called_once_with(
            "CN", "daily_quotes", "tushare", "1970-01-01", 0
        )

    @pytest.mark.asyncio
    async def test_reset_hk_market(self, mock_repo):
        mock_repo.update_checkpoint = AsyncMock()
        mgr = CheckpointManager()
        await mgr.reset_checkpoint("HK", "basic_info", "akshare_hk")
        mock_repo.update_checkpoint.assert_called_once_with(
            "HK", "basic_info", "akshare_hk", "1970-01-01", 0
        )

    @pytest.mark.asyncio
    async def test_reset_us_market(self, mock_repo):
        mock_repo.update_checkpoint = AsyncMock()
        mgr = CheckpointManager()
        await mgr.reset_checkpoint("US", "financial_data", "tushare_us")
        mock_repo.update_checkpoint.assert_called_once_with(
            "US", "financial_data", "tushare_us", "1970-01-01", 0
        )


class TestCheckpointManagerIntegration:
    """检查点管理器组合操作。"""

    @pytest.mark.asyncio
    async def test_get_then_update_flow(self, mock_repo):
        mock_repo.get_checkpoint = AsyncMock(return_value={"last_sync_date": "2024-06-14"})
        mock_repo.update_checkpoint = AsyncMock()
        mgr = CheckpointManager()

        cp = await mgr.get_checkpoint("CN", "daily_quotes", "tushare")
        assert cp == "2024-06-14"

        await mgr.update_checkpoint("CN", "daily_quotes", "tushare", "2024-06-15", 100)
        mock_repo.update_checkpoint.assert_called_once()

    @pytest.mark.asyncio
    async def test_reset_then_get_flow(self, mock_repo):
        mock_repo.update_checkpoint = AsyncMock()
        mock_repo.get_checkpoint = AsyncMock(return_value={"last_sync_date": "1970-01-01"})
        mgr = CheckpointManager()

        await mgr.reset_checkpoint("CN", "daily_quotes", "tushare")
        mock_repo.update_checkpoint.assert_called_once_with(
            "CN", "daily_quotes", "tushare", "1970-01-01", 0
        )

        cp = await mgr.get_checkpoint("CN", "daily_quotes", "tushare")
        assert cp == "1970-01-01"
