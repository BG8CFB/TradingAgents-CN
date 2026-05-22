"""测试 SchedulerEngine — 基于 APScheduler 的调度引擎。

覆盖范围：
- 引擎启动与关闭（mock APScheduler）
- YAML 配置加载与 CronTrigger 创建
- 任务注册与查找
- 手动触发任务
- 状态查询
- _make_job_func 执行逻辑
"""

import os
import pytest
import tempfile
from unittest.mock import AsyncMock, MagicMock, patch

from app.data.scheduler.engine import SchedulerEngine


@pytest.fixture
def engine():
    """创建一个引擎实例，替换内部 scheduler 为 mock。"""
    eng = SchedulerEngine()
    yield eng


@pytest.fixture
def sample_yaml_path():
    """创建临时 YAML 配置文件。"""
    yaml_content = """\
daily_quotes:
  cron: "15 16 * * 1-5"
  timezone: "Asia/Shanghai"
  mode: incremental
basic_info:
  cron: "0 9 * * *"
  timezone: "Asia/Shanghai"
  mode: full
"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False, encoding="utf-8") as f:
        f.write(yaml_content)
        path = f.name
    yield path
    os.unlink(path)


# ---------------------------------------------------------------------------
# 引擎启停测试
# ---------------------------------------------------------------------------
class TestEngineStartStop:
    """测试引擎启动与关闭。"""

    def test_start_registers_jobs_and_loads_schedules(self, engine):
        with patch.object(engine, "_register_all_jobs") as mock_register, \
             patch.object(engine, "_load_all_schedules") as mock_load, \
             patch.object(engine._scheduler, "start") as mock_sched_start:
            engine._scheduler._eventloop = MagicMock()
            engine.start()

        mock_register.assert_called_once()
        mock_load.assert_called_once()
        mock_sched_start.assert_called_once()

    def test_shutdown_calls_scheduler_shutdown_when_running(self, engine):
        with patch.object(engine._scheduler, "shutdown") as mock_shutdown:
            type(engine._scheduler).running = property(lambda self: True)
            try:
                engine.shutdown(wait=False)
                mock_shutdown.assert_called_once_with(wait=False)
            finally:
                del type(engine._scheduler).running

    def test_shutdown_skips_when_not_running(self, engine):
        with patch.object(engine._scheduler, "shutdown") as mock_shutdown:
            type(engine._scheduler).running = property(lambda self: False)
            try:
                engine.shutdown(wait=False)
                mock_shutdown.assert_not_called()
            finally:
                del type(engine._scheduler).running


# ---------------------------------------------------------------------------
# 任务注册测试
# ---------------------------------------------------------------------------
class TestJobRegistration:
    """测试任务注册逻辑。"""

    def test_register_all_jobs_calls_market_registrars(self, engine):
        with patch("app.data.scheduler.jobs.cn.register_cn_jobs") as mock_cn, \
             patch("app.data.scheduler.jobs.hk.register_hk_jobs") as mock_hk, \
             patch("app.data.scheduler.jobs.us.register_us_jobs") as mock_us:
            engine._register_all_jobs()

        mock_cn.assert_called_once_with(engine._registry)
        mock_hk.assert_called_once_with(engine._registry)
        mock_us.assert_called_once_with(engine._registry)
        assert engine._jobs_registered is True

    def test_register_all_jobs_idempotent(self, engine):
        with patch("app.data.scheduler.jobs.cn.register_cn_jobs"), \
             patch("app.data.scheduler.jobs.hk.register_hk_jobs"), \
             patch("app.data.scheduler.jobs.us.register_us_jobs"):
            engine._register_all_jobs()

        with patch("app.data.scheduler.jobs.cn.register_cn_jobs") as mock_cn:
            engine._register_all_jobs()
            mock_cn.assert_not_called()


# ---------------------------------------------------------------------------
# YAML 配置加载测试
# ---------------------------------------------------------------------------
class TestLoadSchedule:
    """测试 YAML 配置加载与 CronTrigger 创建。"""

    def test_load_schedule_registers_jobs(self, engine, sample_yaml_path):
        with patch.object(engine._scheduler, "add_job") as mock_add, \
             patch("app.data.scheduler.engine.CronTrigger", return_value=MagicMock()) as mock_trigger:
            engine.load_schedule("cn", sample_yaml_path)

        assert mock_add.call_count == 2
        job_ids = [call.kwargs.get("id") for call in mock_add.call_args_list]
        assert "cn_daily_quotes" in job_ids
        assert "cn_basic_info" in job_ids

    def test_load_schedule_nonexistent_file(self, engine):
        engine.load_schedule("cn", "/nonexistent/path.yaml")

    def test_load_schedule_no_cron_field_skipped(self, engine):
        yaml_content = """\
daily_quotes:
  timezone: "Asia/Shanghai"
  mode: incremental
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False, encoding="utf-8") as f:
            f.write(yaml_content)
            path = f.name

        try:
            with patch.object(engine._scheduler, "add_job") as mock_add:
                engine.load_schedule("cn", path)
            mock_add.assert_not_called()
        finally:
            os.unlink(path)

    def test_load_schedule_empty_yaml(self, engine):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False, encoding="utf-8") as f:
            f.write("")
            path = f.name

        try:
            with patch.object(engine._scheduler, "add_job") as mock_add:
                engine.load_schedule("cn", path)
            mock_add.assert_not_called()
        finally:
            os.unlink(path)


# ---------------------------------------------------------------------------
# _make_job_func 测试
# ---------------------------------------------------------------------------
class TestMakeJobFunc:
    """测试任务函数创建。"""

    @pytest.mark.asyncio
    async def test_job_func_executes_registered_job(self, engine):
        mock_job_cls = MagicMock()
        mock_instance = MagicMock()
        mock_instance.execute = AsyncMock(return_value={"status": "success"})
        mock_job_cls.return_value = mock_instance

        engine._registry.register("daily_quotes", "CN", mock_job_cls)
        job_func = engine._make_job_func("CN", "daily_quotes")
        await job_func()

        mock_instance.execute.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_job_func_handles_missing_job(self, engine):
        job_func = engine._make_job_func("CN", "unknown_domain")
        await job_func()

    @pytest.mark.asyncio
    async def test_job_func_handles_execution_error(self, engine):
        mock_job_cls = MagicMock()
        mock_instance = MagicMock()
        mock_instance.execute = AsyncMock(side_effect=RuntimeError("sync failed"))
        mock_job_cls.return_value = mock_instance

        engine._registry.register("daily_quotes", "CN", mock_job_cls)
        job_func = engine._make_job_func("CN", "daily_quotes")
        await job_func()


# ---------------------------------------------------------------------------
# 手动触发测试
# ---------------------------------------------------------------------------
class TestTriggerJob:
    """测试手动触发任务。"""

    def test_trigger_job_returns_job_id(self, engine):
        mock_job_cls = MagicMock()
        mock_instance = MagicMock()
        mock_instance.execute = AsyncMock(return_value={"status": "success"})
        mock_job_cls.return_value = mock_instance

        engine._registry.register("daily_quotes", "CN", mock_job_cls)

        with patch("asyncio.create_task") as mock_create_task:
            result = engine.trigger_job("CN", "daily_quotes")

        assert result == "CN_daily_quotes"
        mock_create_task.assert_called_once()

    def test_trigger_job_unregistered_returns_empty(self, engine):
        result = engine.trigger_job("CN", "unknown_domain")
        assert result == ""

    def test_trigger_job_instantiation_error_returns_empty(self, engine):
        mock_job_cls = MagicMock(side_effect=RuntimeError("init failed"))
        engine._registry.register("daily_quotes", "CN", mock_job_cls)
        result = engine.trigger_job("CN", "daily_quotes")
        assert result == ""


# ---------------------------------------------------------------------------
# 状态查询测试
# ---------------------------------------------------------------------------
class TestGetJobStatus:
    """测试任务状态查询。"""

    def test_get_job_status_running(self, engine):
        mock_job = MagicMock()
        mock_job.id = "cn_daily_quotes"
        mock_job.next_run_time = MagicMock()

        with patch.object(engine._scheduler, "get_job", return_value=mock_job):
            status = engine.get_job_status("cn_daily_quotes")

        assert status is not None
        assert status["id"] == "cn_daily_quotes"
        assert status["status"] == "running"

    def test_get_job_status_paused(self, engine):
        mock_job = MagicMock()
        mock_job.id = "cn_daily_quotes"
        mock_job.next_run_time = None

        with patch.object(engine._scheduler, "get_job", return_value=mock_job):
            status = engine.get_job_status("cn_daily_quotes")

        assert status["status"] == "paused"

    def test_get_job_status_not_found(self, engine):
        with patch.object(engine._scheduler, "get_job", return_value=None):
            status = engine.get_job_status("nonexistent_job")
        assert status is None


# ---------------------------------------------------------------------------
# _load_all_schedules 测试
# ---------------------------------------------------------------------------
class TestLoadAllSchedules:
    """测试全市场调度加载。"""

    def test_load_all_schedules_loads_three_markets(self, engine):
        with patch.object(engine, "load_schedule") as mock_load:
            engine._load_all_schedules()

        assert mock_load.call_count == 3
        called_markets = [call[0][0] for call in mock_load.call_args_list]
        assert "cn" in called_markets
        assert "hk" in called_markets
        assert "us" in called_markets
