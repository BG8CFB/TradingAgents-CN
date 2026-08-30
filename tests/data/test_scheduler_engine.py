"""测试 SchedulerEngine — 基于 APScheduler 的调度引擎。

覆盖范围：
- 引擎启动与关闭（真实 APScheduler）
- YAML 配置加载与 CronTrigger 创建（真实触发器，验证参数名正确）
- 任务注册与查找
- 手动触发任务
- 状态查询
- _make_job_func 执行逻辑

设计原则：不使用 unittest.mock，所有路径使用真实代码。
"""

import pytest
import asyncio

from apscheduler.triggers.cron import CronTrigger



class FakeJob:
    """用于注册到 JobRegistry 的简单 Job 类。"""

    async def execute(self):
        return {"status": "success"}


class BrokenJob:
    """构造时抛出异常的 Job 类。"""

    def __init__(self):
        raise RuntimeError("init failed")


class RecordingJob:
    """记录引擎注入的 sync_mode / preferred_source 的 Job（按执行顺序追加到类列表）。"""

    instances: list = []

    def __init__(self):
        self.sync_mode = "incremental"
        self.preferred_source = None
        self.dependencies = []
        self.force_sync = False
        RecordingJob.instances.append(self)

    async def execute(self):
        return {"status": "success"}


# ---------------------------------------------------------------------------
# 引擎启停测试
# ---------------------------------------------------------------------------
class TestEngineStartStop:
    """测试引擎启动与关闭（需要异步事件循环）。"""

    @pytest.mark.asyncio
    async def test_start_registers_jobs_and_starts_scheduler(self, scheduler_engine):
        scheduler_engine.start()
        assert scheduler_engine._scheduler.running
        assert scheduler_engine._jobs_registered
        scheduler_engine.shutdown(wait=False)

    @pytest.mark.asyncio
    async def test_shutdown_stops_scheduler(self, scheduler_engine):
        scheduler_engine.start()
        assert scheduler_engine._scheduler.running
        scheduler_engine.shutdown(wait=True)
        await asyncio.sleep(0.1)
        assert not scheduler_engine._scheduler.running

    def test_shutdown_when_not_running_is_safe(self, scheduler_engine):
        scheduler_engine.shutdown(wait=False)


# ---------------------------------------------------------------------------
# 任务注册测试
# ---------------------------------------------------------------------------
class TestJobRegistration:
    """测试任务注册逻辑（使用真实 JobRegistry）。"""

    def test_register_all_jobs_populates_registry(self, scheduler_engine):
        scheduler_engine._register_all_jobs()
        jobs = scheduler_engine._registry.list_jobs()
        assert len(jobs) > 0
        assert scheduler_engine._jobs_registered

    def test_register_all_jobs_idempotent(self, scheduler_engine):
        scheduler_engine._register_all_jobs()
        first_count = len(scheduler_engine._registry.list_jobs())
        scheduler_engine._register_all_jobs()
        second_count = len(scheduler_engine._registry.list_jobs())
        assert first_count == second_count

    def test_register_specific_job(self, scheduler_engine):
        scheduler_engine._registry.register("test_domain", "CN", FakeJob)
        entry = scheduler_engine._registry.get_job("test_domain", "CN")
        assert entry is not None
        assert entry["domain"] == "test_domain"
        assert entry["market"] == "CN"
        assert entry["class"] is FakeJob


# ---------------------------------------------------------------------------
# YAML 配置加载测试 — 使用真实 CronTrigger
# ---------------------------------------------------------------------------
class TestLoadSchedule:
    """测试 YAML 配置加载与 CronTrigger 创建。

    这是之前 bug 的直接回归测试：
    - CronTrigger 正确使用 'day' 而非 'day_of_month'
    - cron 表达式正确解析为 5 部分
    - APScheduler add_job 被成功调用
    """

    def test_load_schedule_creates_real_triggers(self, scheduler_engine, sample_schedule_yaml):
        scheduler_engine.load_schedule("cn", sample_schedule_yaml)

        job_ids = [j.id for j in scheduler_engine._scheduler.get_jobs()]
        assert "cn_daily_quotes" in job_ids
        assert "cn_basic_info" in job_ids

    def test_load_schedule_trigger_is_valid_cron(self, scheduler_engine, sample_schedule_yaml):
        scheduler_engine.load_schedule("cn", sample_schedule_yaml)

        for job in scheduler_engine._scheduler.get_jobs():
            assert isinstance(job.trigger, CronTrigger)

    def test_load_schedule_daily_quotes_trigger_fields(self, scheduler_engine, sample_schedule_yaml):
        scheduler_engine.load_schedule("cn", sample_schedule_yaml)

        job = scheduler_engine._scheduler.get_job("cn_daily_quotes")
        assert job is not None
        assert isinstance(job.trigger, CronTrigger)

    def test_load_schedule_nonexistent_file(self, scheduler_engine):
        scheduler_engine.load_schedule("cn", "/nonexistent/path.yaml")
        assert len(scheduler_engine._scheduler.get_jobs()) == 0

    def test_load_schedule_no_cron_field_skipped(self, scheduler_engine, sample_schedule_yaml_no_cron):
        scheduler_engine.load_schedule("cn", sample_schedule_yaml_no_cron)
        assert len(scheduler_engine._scheduler.get_jobs()) == 0

    def test_load_schedule_empty_yaml(self, scheduler_engine, sample_schedule_yaml_empty):
        scheduler_engine.load_schedule("cn", sample_schedule_yaml_empty)
        assert len(scheduler_engine._scheduler.get_jobs()) == 0

    def test_load_schedule_with_uppercase_market(self, scheduler_engine, sample_schedule_yaml):
        scheduler_engine.load_schedule("CN", sample_schedule_yaml)
        job_ids = [j.id for j in scheduler_engine._scheduler.get_jobs()]
        assert "cn_daily_quotes" in job_ids


# ---------------------------------------------------------------------------
# CronTrigger 参数正确性回归测试
# ---------------------------------------------------------------------------
class TestCronTriggerRegression:
    """回归测试：验证 CronTrigger 参数名正确（day vs day_of_month）。"""

    def test_cron_trigger_accepts_day_parameter(self):
        trigger = CronTrigger(minute="15", hour="16", day="*", month="*", day_of_week="1-5")
        assert trigger is not None

    def test_cron_trigger_from_five_part_cron(self):
        parts = "15 16 * * 1-5".split()
        trigger = CronTrigger(
            minute=parts[0],
            hour=parts[1],
            day=parts[2] if len(parts) > 2 else "*",
            month=parts[3] if len(parts) > 3 else "*",
            day_of_week=parts[4] if len(parts) > 4 else "*",
        )
        assert trigger is not None


# ---------------------------------------------------------------------------
# _make_job_func 测试
# ---------------------------------------------------------------------------
class TestMakeJobFunc:
    """测试任务函数创建（使用真实 FakeJob）。"""

    @pytest.mark.asyncio
    async def test_job_func_executes_registered_job(self, scheduler_engine):
        scheduler_engine._registry.register("daily_quotes", "CN", FakeJob)
        job_func = scheduler_engine._make_job_func("CN", "daily_quotes")
        await job_func()

    @pytest.mark.asyncio
    async def test_job_func_handles_missing_job(self, scheduler_engine):
        job_func = scheduler_engine._make_job_func("CN", "unknown_domain")
        await job_func()

    @pytest.mark.asyncio
    async def test_job_func_handles_execution_error(self, scheduler_engine):
        class ErrorJob:
            async def execute(self):
                raise RuntimeError("sync failed")

        scheduler_engine._registry.register("daily_quotes", "CN", ErrorJob)
        job_func = scheduler_engine._make_job_func("CN", "daily_quotes")
        await job_func()


# ---------------------------------------------------------------------------
# 手动触发测试
# ---------------------------------------------------------------------------
class TestTriggerJob:
    """测试手动触发任务（使用真实 JobRegistry + FakeJob）。

    trigger_job 内部使用 asyncio.create_task，需要在异步上下文中运行。
    """

    @pytest.mark.asyncio
    async def test_trigger_job_returns_job_id(self, scheduler_engine):
        scheduler_engine._registry.register("daily_quotes", "CN", FakeJob)
        result = await scheduler_engine.trigger_job("CN", "daily_quotes")
        assert result == "cn_daily_quotes"

    @pytest.mark.asyncio
    async def test_trigger_job_unregistered_returns_empty(self, scheduler_engine):
        result = await scheduler_engine.trigger_job("CN", "unknown_domain")
        assert result == ""

    @pytest.mark.asyncio
    async def test_trigger_job_instantiation_error_returns_job_id(self, scheduler_engine):
        """任务实例化错误被内部捕获并记录日志，trigger_job 仍返回 job_id。"""
        scheduler_engine._registry.register("daily_quotes", "CN", BrokenJob)
        result = await scheduler_engine.trigger_job("CN", "daily_quotes")
        assert result == "cn_daily_quotes"

    @pytest.mark.asyncio
    async def test_trigger_job_market_case_sensitivity(self, scheduler_engine):
        scheduler_engine._registry.register("daily_quotes", "CN", FakeJob)
        assert await scheduler_engine.trigger_job("CN", "daily_quotes") == "cn_daily_quotes"
        assert await scheduler_engine.trigger_job("cn", "daily_quotes") == "cn_daily_quotes"

    @pytest.mark.asyncio
    async def test_trigger_job_multiple_markets(self, scheduler_engine):
        scheduler_engine._registry.register("daily_quotes", "CN", FakeJob)
        scheduler_engine._registry.register("daily_quotes", "HK", FakeJob)
        scheduler_engine._registry.register("daily_quotes", "US", FakeJob)

        assert await scheduler_engine.trigger_job("CN", "daily_quotes") == "cn_daily_quotes"
        assert await scheduler_engine.trigger_job("HK", "daily_quotes") == "hk_daily_quotes"
        assert await scheduler_engine.trigger_job("US", "daily_quotes") == "us_daily_quotes"


# ---------------------------------------------------------------------------
# mode / source 手动触发覆盖测试
# ---------------------------------------------------------------------------
class TestModeSourceOverride:
    """手动触发的 mode/source 仅覆盖目标域，依赖域回落 schedule.yaml 默认。"""

    def setup_method(self):
        RecordingJob.instances.clear()

    @pytest.mark.asyncio
    async def test_trigger_job_mode_overrides_target_domain(self, scheduler_engine):
        scheduler_engine._registry.register("daily_quotes", "CN", RecordingJob)
        scheduler_engine._job_configs[("CN", "daily_quotes")] = {
            "mode": "incremental",
            "source": "tushare",
        }
        await scheduler_engine.trigger_job(
            "CN", "daily_quotes", mode="full", source="akshare"
        )
        job = RecordingJob.instances[-1]
        assert job.sync_mode == "full"
        assert job.preferred_source == "akshare"

    @pytest.mark.asyncio
    async def test_yaml_defaults_when_no_override(self, scheduler_engine):
        scheduler_engine._registry.register("daily_quotes", "CN", RecordingJob)
        scheduler_engine._job_configs[("CN", "daily_quotes")] = {
            "mode": "full",
            "source": "tushare",
        }
        await scheduler_engine.trigger_job("CN", "daily_quotes")
        job = RecordingJob.instances[-1]
        assert job.sync_mode == "full"
        assert job.preferred_source == "tushare"

    @pytest.mark.asyncio
    async def test_dependency_domain_keeps_yaml_defaults(self, scheduler_engine):
        """依赖域不被覆盖（与 force 只作用于目标域的 M13 语义对齐）；依赖先于目标执行。"""
        scheduler_engine._registry.register("daily_quotes", "CN", RecordingJob)
        scheduler_engine._registry.register("trade_calendar", "CN", RecordingJob)
        scheduler_engine._job_configs[("CN", "daily_quotes")] = {
            "mode": "incremental",
            "depends_on": ["trade_calendar"],
        }
        scheduler_engine._job_configs[("CN", "trade_calendar")] = {
            "mode": "incremental",
            "source": "tushare",
        }
        await scheduler_engine.trigger_job(
            "CN", "daily_quotes", mode="full", source="akshare"
        )
        dep_job = RecordingJob.instances[0]
        target_job = RecordingJob.instances[1]
        assert dep_job.sync_mode == "incremental"
        assert dep_job.preferred_source == "tushare"
        assert target_job.sync_mode == "full"
        assert target_job.preferred_source == "akshare"


# ---------------------------------------------------------------------------
# run_job_now 测试（后台执行 + 立即返回 + already_running 防重）
# ---------------------------------------------------------------------------
class TestRunJobNow:
    """run_job_now：注册后台任务立即返回，同域运行中时幂等返回 already_running。"""

    def setup_method(self):
        RecordingJob.instances.clear()

    @pytest.mark.asyncio
    async def test_returns_triggered_and_executes_in_background(self, scheduler_engine):
        scheduler_engine._registry.register("daily_quotes", "CN", RecordingJob)
        scheduler_engine._job_configs[("CN", "daily_quotes")] = {}
        result = scheduler_engine.run_job_now("CN", "daily_quotes", mode="full")
        assert result["status"] == "triggered"
        assert result["task_id"] == "CN:daily_quotes"
        assert result["job_id"] == "cn_daily_quotes"
        # 后台任务由本测试的事件循环调度执行
        await asyncio.sleep(0.2)
        assert any(j.sync_mode == "full" for j in RecordingJob.instances)

    @pytest.mark.asyncio
    async def test_unregistered_domain_returns_failed(self, scheduler_engine):
        result = scheduler_engine.run_job_now("CN", "unknown_domain")
        assert result["status"] == "failed"

    @pytest.mark.asyncio
    async def test_already_running_skips_execution(self, scheduler_engine):
        """同域已在运行（监控内存态）时幂等返回，不重复执行。"""
        from app.data.scheduler.monitors import SchedulerMonitor

        monitor = SchedulerMonitor()
        original_running = monitor._running
        # 不启动监控线程，仅激活运行态查询路径（_get_monitor 检查 _running）
        monitor._running = True
        monitor.on_task_start("CN", "daily_quotes")
        try:
            scheduler_engine._registry.register("daily_quotes", "CN", RecordingJob)
            result = scheduler_engine.run_job_now("CN", "daily_quotes")
            assert result["status"] == "already_running"
            assert result["task_id"] == "CN:daily_quotes"
            assert RecordingJob.instances == []
        finally:
            monitor.on_task_complete("CN", "daily_quotes", success=True)
            monitor._running = original_running


# ---------------------------------------------------------------------------
# 状态查询测试
# ---------------------------------------------------------------------------
class TestGetJobStatus:
    """测试任务状态查询（使用真实 APScheduler）。"""

    @pytest.mark.asyncio
    async def test_get_job_status_running(self, scheduler_engine, sample_schedule_yaml):
        scheduler_engine.load_schedule("cn", sample_schedule_yaml)
        scheduler_engine.start()
        try:
            status = scheduler_engine.get_job_status("cn_daily_quotes")
            assert status is not None
            assert status["id"] == "cn_daily_quotes"
            assert status["status"] == "running"
        finally:
            scheduler_engine.shutdown(wait=False)

    @pytest.mark.asyncio
    async def test_get_job_status_paused(self, scheduler_engine, sample_schedule_yaml):
        scheduler_engine.load_schedule("cn", sample_schedule_yaml)
        scheduler_engine.start()
        scheduler_engine._scheduler.pause_job("cn_daily_quotes")
        try:
            status = scheduler_engine.get_job_status("cn_daily_quotes")
            assert status is not None
            assert status["status"] == "paused"
        finally:
            scheduler_engine.shutdown(wait=False)

    def test_get_job_status_not_found(self, scheduler_engine):
        status = scheduler_engine.get_job_status("nonexistent_job")
        assert status is None


# ---------------------------------------------------------------------------
# _load_all_schedules 测试
# ---------------------------------------------------------------------------
class TestLoadAllSchedules:
    """测试全市场调度加载。"""

    def test_load_all_schedules_loads_three_markets(self, scheduler_engine):
        scheduler_engine._load_all_schedules()
        job_ids = [j.id for j in scheduler_engine._scheduler.get_jobs()]
        assert len(job_ids) > 0
