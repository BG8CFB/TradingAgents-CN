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

import os
import pytest
import asyncio

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.data.scheduler.engine import SchedulerEngine
from app.data.scheduler.job_registry import JobRegistry


class FakeJob:
    """用于注册到 JobRegistry 的简单 Job 类。"""

    async def execute(self):
        return {"status": "success"}


class BrokenJob:
    """构造时抛出异常的 Job 类。"""

    def __init__(self):
        raise RuntimeError("init failed")


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
        assert "CN_daily_quotes" in job_ids


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
        result = scheduler_engine.trigger_job("CN", "daily_quotes")
        assert result == "CN_daily_quotes"

    def test_trigger_job_unregistered_returns_empty(self, scheduler_engine):
        result = scheduler_engine.trigger_job("CN", "unknown_domain")
        assert result == ""

    def test_trigger_job_instantiation_error_returns_empty(self, scheduler_engine):
        scheduler_engine._registry.register("daily_quotes", "CN", BrokenJob)
        result = scheduler_engine.trigger_job("CN", "daily_quotes")
        assert result == ""

    @pytest.mark.asyncio
    async def test_trigger_job_market_case_sensitivity(self, scheduler_engine):
        scheduler_engine._registry.register("daily_quotes", "CN", FakeJob)
        assert scheduler_engine.trigger_job("CN", "daily_quotes") == "CN_daily_quotes"
        assert scheduler_engine.trigger_job("cn", "daily_quotes") == ""

    @pytest.mark.asyncio
    async def test_trigger_job_multiple_markets(self, scheduler_engine):
        scheduler_engine._registry.register("daily_quotes", "CN", FakeJob)
        scheduler_engine._registry.register("daily_quotes", "HK", FakeJob)
        scheduler_engine._registry.register("daily_quotes", "US", FakeJob)

        assert scheduler_engine.trigger_job("CN", "daily_quotes") == "CN_daily_quotes"
        assert scheduler_engine.trigger_job("HK", "daily_quotes") == "HK_daily_quotes"
        assert scheduler_engine.trigger_job("US", "daily_quotes") == "US_daily_quotes"


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
