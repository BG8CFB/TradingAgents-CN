"""
定时任务注册模块

从 app/main.py lifespan 中提取，统一管理所有 APScheduler 定时任务。
使用新架构 SchedulerEngine 管理三市场域级同步。
"""

import asyncio
import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from app.core.config import settings

logger = logging.getLogger("app.scheduler_setup")


def add_resilient_job(sched: AsyncIOScheduler, func, trigger, **kwargs):
    """添加具有容错能力的定时任务。"""
    defaults = {
        "max_instances": 1,
        "misfire_grace_time": 600,
        "coalesce": True,
        "replace_existing": True,
    }
    defaults.update(kwargs)
    sched.add_job(func, trigger, **defaults)


async def register_jobs(scheduler: AsyncIOScheduler, basics_sync_service, run_basics_sync_func):
    """
    注册所有定时任务。

    使用 SchedulerEngine 管理三市场域级同步，同时在主调度器上
    注册基础信息同步和实时行情入库等非域级任务。

    Args:
        scheduler: APScheduler AsyncIOScheduler 实例
        basics_sync_service: MultiSourceBasicsSyncService 实例
        run_basics_sync_func: 模块级基础信息同步函数
    """
    tz = settings.TIMEZONE

    # ── 启动新架构 SchedulerEngine（三市场域级同步）──
    _start_scheduler_engine(scheduler)

    # ── Basics sync（多数据源基础信息同步）──
    preferred_sources = None
    if settings.TUSHARE_ENABLED:
        preferred_sources = ["tushare", "akshare", "baostock"]
        logger.info("股票基础信息同步优先数据源: Tushare > AKShare > BaoStock")
    else:
        preferred_sources = ["akshare", "baostock"]
        logger.info("股票基础信息同步优先数据源: AKShare > BaoStock (Tushare已禁用)")

    _startup_sync_lock = asyncio.Lock()

    async def _run_startup_sync():
        if _startup_sync_lock.locked():
            logger.info("启动期同步已被锁定（可能正在执行），跳过")
            return
        async with _startup_sync_lock:
            await run_basics_sync_func(force=False, preferred_sources=preferred_sources)

    _sync_task = asyncio.create_task(_run_startup_sync())
    _sync_task.add_done_callback(_handle_basics_sync_task_result)

    if settings.SYNC_STOCK_BASICS_ENABLED:
        sync_kwargs = {"force": False, "preferred_sources": preferred_sources}
        if settings.SYNC_STOCK_BASICS_CRON:
            add_resilient_job(
                scheduler, run_basics_sync_func,
                CronTrigger.from_crontab(settings.SYNC_STOCK_BASICS_CRON, timezone=tz),
                id="basics_sync_service",
                name="股票基础信息同步（多数据源）",
                kwargs=sync_kwargs,
            )
            logger.info(f"Stock basics sync scheduled by CRON: {settings.SYNC_STOCK_BASICS_CRON} ({tz})")
        else:
            hh, mm = (settings.SYNC_STOCK_BASICS_TIME or "06:30").split(":")
            add_resilient_job(
                scheduler, run_basics_sync_func,
                CronTrigger(hour=int(hh), minute=int(mm), timezone=tz),
                id="basics_sync_service",
                name="股票基础信息同步（多数据源）",
                kwargs=sync_kwargs,
            )
            logger.info(f"Stock basics sync scheduled daily at {settings.SYNC_STOCK_BASICS_TIME} ({tz})")

    # ── Quotes ingestion（实时行情入库）──
    if settings.QUOTES_INGEST_ENABLED:
        from app.services.quotes_ingestion_service import QuotesIngestionService

        quotes_ingestion = QuotesIngestionService()
        await quotes_ingestion.ensure_indexes()
        add_resilient_job(
            scheduler, quotes_ingestion.run_once,
            IntervalTrigger(seconds=settings.QUOTES_INGEST_INTERVAL_SECONDS, timezone=tz),
            id="quotes_ingestion_service",
            name="实时行情入库服务",
        )
        logger.info(f"实时行情入库任务已启动: 每 {settings.QUOTES_INGEST_INTERVAL_SECONDS}s")

    # ── A 股数据完整性检查 ──
    add_resilient_job(
        scheduler, _run_cn_integrity_check,
        CronTrigger(hour=17, minute=0, timezone=tz),
        id="cn_integrity_check",
        name="A股数据完整性检查",
    )
    logger.info("A股完整性检查已配置: 每日 17:00")

    # ── 港股全量同步（通过 SchedulerEngine 已自动注册，此处仅注册状态检查等辅助任务）──
    _register_hk_auxiliary_jobs(scheduler)
    _register_us_auxiliary_jobs(scheduler)


def _start_scheduler_engine(scheduler: AsyncIOScheduler):
    """启动新架构 SchedulerEngine，将域级同步任务注册到主调度器上。"""
    try:
        from app.data.scheduler.engine import SchedulerEngine

        engine = SchedulerEngine(scheduler=scheduler)
        engine._register_all_jobs()
        engine._load_all_schedules()

        SchedulerEngine._instance = engine
        logger.info("SchedulerEngine 已集成到主调度器")
    except Exception as e:
        logger.error(f"SchedulerEngine 启动失败: {e}", exc_info=True)


def get_scheduler_engine():
    """获取全局 SchedulerEngine 实例。"""
    from app.data.scheduler.engine import SchedulerEngine
    return getattr(SchedulerEngine, '_instance', None)


def _handle_basics_sync_task_result(task: asyncio.Task) -> None:
    if task.cancelled():
        logger.warning("启动期基础信息同步任务已取消")
        return
    try:
        task.result()
    except Exception as exc:
        logger.error(f"启动期基础信息同步任务失败: {exc}", exc_info=True)


def _register_hk_auxiliary_jobs(sched: AsyncIOScheduler):
    """注册港股辅助任务（基础信息同步 + 日线同步 + 状态检查，默认暂停）。"""
    from app.worker.hk.hk_sync_service import (
        run_hk_basic_info_sync, run_hk_daily_quotes_sync, run_hk_status_check,
    )
    tz = settings.TIMEZONE

    add_resilient_job(
        sched, run_hk_basic_info_sync,
        CronTrigger.from_crontab(settings.HK_BASIC_INFO_SYNC_CRON, timezone=tz),
        id="hk_basic_info_sync",
        name="港股基础信息同步",
        kwargs={"force_update": False},
    )
    if not (settings.HK_UNIFIED_ENABLED and settings.HK_BASIC_INFO_SYNC_ENABLED):
        sched.pause_job("hk_basic_info_sync")

    add_resilient_job(
        sched, run_hk_daily_quotes_sync,
        CronTrigger.from_crontab(settings.HK_DAILY_QUOTES_SYNC_CRON, timezone=tz),
        id="hk_daily_quotes_sync",
        name="港股日线行情同步",
        kwargs={"incremental": True},
    )
    if not (settings.HK_UNIFIED_ENABLED and settings.HK_DAILY_QUOTES_SYNC_ENABLED):
        sched.pause_job("hk_daily_quotes_sync")

    add_resilient_job(
        sched, run_hk_status_check,
        CronTrigger.from_crontab(settings.HK_STATUS_CHECK_CRON, timezone=tz),
        id="hk_status_check",
        name="港股数据源状态检查",
    )
    if not (settings.HK_UNIFIED_ENABLED and settings.HK_STATUS_CHECK_ENABLED):
        sched.pause_job("hk_status_check")


def _register_us_auxiliary_jobs(sched: AsyncIOScheduler):
    """注册美股辅助任务（基础信息同步 + 日线同步 + 状态检查，默认暂停）。"""
    from app.worker.us.us_sync_service import (
        run_us_basic_info_sync, run_us_daily_quotes_sync, run_us_status_check,
    )
    tz = settings.TIMEZONE

    add_resilient_job(
        sched, run_us_basic_info_sync,
        CronTrigger.from_crontab(settings.US_BASIC_INFO_SYNC_CRON, timezone=tz),
        id="us_basic_info_sync",
        name="美股基础信息同步",
        kwargs={"force_update": False},
    )
    if not (settings.US_UNIFIED_ENABLED and settings.US_BASIC_INFO_SYNC_ENABLED):
        sched.pause_job("us_basic_info_sync")

    add_resilient_job(
        sched, run_us_daily_quotes_sync,
        CronTrigger.from_crontab(settings.US_DAILY_QUOTES_SYNC_CRON, timezone=tz),
        id="us_daily_quotes_sync",
        name="美股日线行情同步",
        kwargs={"incremental": True},
    )
    if not (settings.US_UNIFIED_ENABLED and settings.US_DAILY_QUOTES_SYNC_ENABLED):
        sched.pause_job("us_daily_quotes_sync")

    add_resilient_job(
        sched, run_us_status_check,
        CronTrigger.from_crontab(settings.US_STATUS_CHECK_CRON, timezone=tz),
        id="us_status_check",
        name="美股数据源状态检查",
    )
    if not (settings.US_UNIFIED_ENABLED and settings.US_STATUS_CHECK_ENABLED):
        sched.pause_job("us_status_check")


# ── 辅助异步任务函数 ──

async def _run_cn_integrity_check():
    """A股数据完整性检查"""
    try:
        from app.services.cn_data_integrity_service import get_integrity_service
        service = get_integrity_service()
        report = await service.run_full_check()
        logger.info("完整性检查完成: errors=%d, warnings=%d", report.error_count, report.warning_count)
    except Exception as e:
        logger.error(f"完整性检查失败: {e}", exc_info=True)
