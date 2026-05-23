"""检查点管理器测试 — 使用 SimulatedMongoDB 替代 mock。

覆盖范围：
- get_checkpoint — 获取检查点日期
- update_checkpoint — 更新检查点
- reset_checkpoint — 重置为 epoch 日期
- 组合操作：get → update → get 流程

设计原则：不使用 unittest.mock，通过 inject_sim_db 注入内存 MongoDB。
"""

import pytest

from app.data.scheduler.checkpoint import CheckpointManager


class TestGetCheckpoint:
    """获取检查点。"""

    @pytest.mark.asyncio
    async def test_returns_none_when_no_checkpoint(self, checkpoint_manager):
        result = await checkpoint_manager.get_checkpoint("CN", "daily_quotes", "tushare")
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_last_sync_date_after_update(self, checkpoint_manager):
        await checkpoint_manager.update_checkpoint("CN", "daily_quotes", "tushare", "2024-06-15", 100)
        result = await checkpoint_manager.get_checkpoint("CN", "daily_quotes", "tushare")
        assert result == "2024-06-15"


class TestUpdateCheckpoint:
    """更新检查点。"""

    @pytest.mark.asyncio
    async def test_update_then_read(self, checkpoint_manager):
        await checkpoint_manager.update_checkpoint("CN", "daily_quotes", "tushare", "2024-06-15", 500)
        cp = await checkpoint_manager.get_checkpoint("CN", "daily_quotes", "tushare")
        assert cp == "2024-06-15"

    @pytest.mark.asyncio
    async def test_update_with_different_market(self, checkpoint_manager):
        await checkpoint_manager.update_checkpoint("HK", "basic_info", "akshare_hk", "2024-01-01", 50)
        cp = await checkpoint_manager.get_checkpoint("HK", "basic_info", "akshare_hk")
        assert cp == "2024-01-01"

    @pytest.mark.asyncio
    async def test_update_with_zero_count(self, checkpoint_manager):
        await checkpoint_manager.update_checkpoint("US", "daily_quotes", "yfinance", "2024-03-01", 0)
        cp = await checkpoint_manager.get_checkpoint("US", "daily_quotes", "yfinance")
        assert cp == "2024-03-01"

    @pytest.mark.asyncio
    async def test_update_overwrites_previous(self, checkpoint_manager):
        await checkpoint_manager.update_checkpoint("CN", "daily_quotes", "tushare", "2024-06-14", 100)
        await checkpoint_manager.update_checkpoint("CN", "daily_quotes", "tushare", "2024-06-15", 200)
        cp = await checkpoint_manager.get_checkpoint("CN", "daily_quotes", "tushare")
        assert cp == "2024-06-15"


class TestResetCheckpoint:
    """重置检查点（强制全量同步）。"""

    @pytest.mark.asyncio
    async def test_reset_sets_epoch_date(self, checkpoint_manager):
        await checkpoint_manager.update_checkpoint("CN", "daily_quotes", "tushare", "2024-06-15", 100)
        await checkpoint_manager.reset_checkpoint("CN", "daily_quotes", "tushare")
        cp = await checkpoint_manager.get_checkpoint("CN", "daily_quotes", "tushare")
        assert cp == "1970-01-01"

    @pytest.mark.asyncio
    async def test_reset_hk_market(self, checkpoint_manager):
        await checkpoint_manager.reset_checkpoint("HK", "basic_info", "akshare_hk")
        cp = await checkpoint_manager.get_checkpoint("HK", "basic_info", "akshare_hk")
        assert cp == "1970-01-01"

    @pytest.mark.asyncio
    async def test_reset_us_market(self, checkpoint_manager):
        await checkpoint_manager.reset_checkpoint("US", "financial_data", "tushare_us")
        cp = await checkpoint_manager.get_checkpoint("US", "financial_data", "tushare_us")
        assert cp == "1970-01-01"


class TestCheckpointManagerIntegration:
    """检查点管理器组合操作。"""

    @pytest.mark.asyncio
    async def test_get_then_update_flow(self, checkpoint_manager):
        cp = await checkpoint_manager.get_checkpoint("CN", "daily_quotes", "tushare")
        assert cp is None

        await checkpoint_manager.update_checkpoint("CN", "daily_quotes", "tushare", "2024-06-15", 100)
        cp = await checkpoint_manager.get_checkpoint("CN", "daily_quotes", "tushare")
        assert cp == "2024-06-15"

    @pytest.mark.asyncio
    async def test_reset_then_get_flow(self, checkpoint_manager):
        await checkpoint_manager.update_checkpoint("CN", "daily_quotes", "tushare", "2024-06-15", 100)
        await checkpoint_manager.reset_checkpoint("CN", "daily_quotes", "tushare")
        cp = await checkpoint_manager.get_checkpoint("CN", "daily_quotes", "tushare")
        assert cp == "1970-01-01"

    @pytest.mark.asyncio
    async def test_multiple_sources_independent(self, checkpoint_manager):
        await checkpoint_manager.update_checkpoint("CN", "daily_quotes", "tushare", "2024-06-15", 100)
        await checkpoint_manager.update_checkpoint("CN", "daily_quotes", "akshare", "2024-06-14", 90)

        cp_ts = await checkpoint_manager.get_checkpoint("CN", "daily_quotes", "tushare")
        cp_ak = await checkpoint_manager.get_checkpoint("CN", "daily_quotes", "akshare")
        assert cp_ts == "2024-06-15"
        assert cp_ak == "2024-06-14"
