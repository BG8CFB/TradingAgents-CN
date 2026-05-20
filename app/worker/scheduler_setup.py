"""
定时任务注册模块

从 app/main.py lifespan 中提取，统一管理所有 APScheduler 定时任务的注册。
Phase 4G：将 main.py 中约 300 行 cron 配置代码提取到此处。
"""

import asyncio
import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from app.core.config import settings
from app.utils.timezone import now_utc

logger = logging.getLogger("app.scheduler_setup")


# ── 容错配置辅助函数 ──────────────────────────────────────────────────

def add_resilient_job(sched: AsyncIOScheduler, func, trigger, **kwargs):
    """
    添加具有容错能力的定时任务。

    参数:
        id: 任务ID（必需）
        name: 任务名称（必需）
        max_instances: 最大并发实例数（防止任务重叠）
        misfire_grace_time: 错过执行的宽限时间（秒）
        coalesce: 多次misfire合并为一次执行
        replace_existing: 替换已存在的同ID任务
    """
    defaults = {
        "max_instances": 1,
        "misfire_grace_time": 600,
        "coalesce": True,
        "replace_existing": True,
    }
    defaults.update(kwargs)
    sched.add_job(func, trigger, **defaults)


# ── 主注册入口 ───────────────────────────────────────────────────────

async def register_jobs(
    scheduler: AsyncIOScheduler,
    basics_sync_service,
    run_basics_sync_func,
):
    """
    注册所有定时任务。

    Args:
        scheduler: APScheduler AsyncIOScheduler 实例
        basics_sync_service: MultiSourceBasicsSyncService 实例
        run_basics_sync_func: 模块级基础信息同步函数（APScheduler 要求可被模块路径引用）
    """
    tz = settings.TIMEZONE

    # ── Basics sync（多数据源基础信息同步）──────────────────────────────
    preferred_sources = None
    if settings.TUSHARE_ENABLED:
        preferred_sources = ["tushare", "akshare", "baostock"]
        logger.info("股票基础信息同步优先数据源: Tushare > AKShare > BaoStock")
    else:
        preferred_sources = ["akshare", "baostock"]
        logger.info("股票基础信息同步优先数据源: AKShare > BaoStock (Tushare已禁用)")

    # 启动后立即执行一次（带并发锁保护，防止与定时任务重叠）
    _startup_sync_lock = asyncio.Lock()

    async def _run_startup_sync():
        """启动期同步：通过锁保护，避免与定时任务并发执行"""
        if _startup_sync_lock.locked():
            logger.info("启动期同步已被锁定（可能正在执行），跳过")
            return
        async with _startup_sync_lock:
            await run_basics_sync_func(force=False, preferred_sources=preferred_sources)

    _sync_task = asyncio.create_task(_run_startup_sync())
    _sync_task.add_done_callback(_handle_basics_sync_task_result)

    # 定时 basics sync
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

    # ── Quotes ingestion（实时行情入库，内部自判交易时段）─────────────────
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

    # ── A 股域级编排同步（替代旧数据源任务）───────────────────────────
    _register_cn_domain_jobs(scheduler)

    # ── 港股/美股全量同步（默认暂停，用户通过 .env 启用）────────────────
    logger.info("配置港股统一数据同步任务...")
    _register_hk_jobs(scheduler)
    logger.info("配置美股统一数据同步任务...")
    _register_us_jobs(scheduler)


def _handle_basics_sync_task_result(task: asyncio.Task) -> None:
    """记录启动期基础信息同步任务的执行结果，避免后台异常被静默忽略。"""
    if task.cancelled():
        logger.warning("启动期基础信息同步任务已取消")
        return
    try:
        task.result()
    except Exception as exc:
        logger.error(f"启动期基础信息同步任务失败: {exc}", exc_info=True)


def _register_hk_jobs(sched: AsyncIOScheduler):
    """注册港股全量同步任务（3 个 job，默认暂停）"""
    from app.worker.hk import (
        run_hk_basic_info_sync,
        run_hk_daily_quotes_sync,
        run_hk_status_check,
    )

    tz = settings.TIMEZONE

    # 基础信息同步
    add_resilient_job(
        sched, run_hk_basic_info_sync,
        CronTrigger.from_crontab(settings.HK_BASIC_INFO_SYNC_CRON, timezone=tz),
        id="hk_basic_info_sync",
        name="港股基础信息同步",
        kwargs={"force_update": False},
    )
    if not (settings.HK_UNIFIED_ENABLED and settings.HK_BASIC_INFO_SYNC_ENABLED):
        sched.pause_job("hk_basic_info_sync")
        logger.info(f"港股基础信息同步已添加但暂停: {settings.HK_BASIC_INFO_SYNC_CRON}")
    else:
        logger.info(f"港股基础信息同步已配置: {settings.HK_BASIC_INFO_SYNC_CRON}")

    # 日线行情同步
    add_resilient_job(
        sched, run_hk_daily_quotes_sync,
        CronTrigger.from_crontab(settings.HK_DAILY_QUOTES_SYNC_CRON, timezone=tz),
        id="hk_daily_quotes_sync",
        name="港股日线行情同步",
        kwargs={"incremental": True},
    )
    if not (settings.HK_UNIFIED_ENABLED and settings.HK_DAILY_QUOTES_SYNC_ENABLED):
        sched.pause_job("hk_daily_quotes_sync")
        logger.info(f"港股日线行情同步已添加但暂停: {settings.HK_DAILY_QUOTES_SYNC_CRON}")
    else:
        logger.info(f"港股日线行情同步已配置: {settings.HK_DAILY_QUOTES_SYNC_CRON}")

    # 状态检查
    add_resilient_job(
        sched, run_hk_status_check,
        CronTrigger.from_crontab(settings.HK_STATUS_CHECK_CRON, timezone=tz),
        id="hk_status_check",
        name="港股数据源状态检查",
    )
    if not (settings.HK_UNIFIED_ENABLED and settings.HK_STATUS_CHECK_ENABLED):
        sched.pause_job("hk_status_check")
        logger.info(f"港股状态检查已添加但暂停: {settings.HK_STATUS_CHECK_CRON}")
    else:
        logger.info(f"港股状态检查已配置: {settings.HK_STATUS_CHECK_CRON}")


def _register_us_jobs(sched: AsyncIOScheduler):
    """注册美股全量同步任务（3 个 job，默认暂停）"""
    from app.worker.us import (
        run_us_basic_info_sync,
        run_us_daily_quotes_sync,
        run_us_status_check,
    )

    tz = settings.TIMEZONE

    # 基础信息同步
    add_resilient_job(
        sched, run_us_basic_info_sync,
        CronTrigger.from_crontab(settings.US_BASIC_INFO_SYNC_CRON, timezone=tz),
        id="us_basic_info_sync",
        name="美股基础信息同步",
        kwargs={"force_update": False},
    )
    if not (settings.US_UNIFIED_ENABLED and settings.US_BASIC_INFO_SYNC_ENABLED):
        sched.pause_job("us_basic_info_sync")
        logger.info(f"美股基础信息同步已添加但暂停: {settings.US_BASIC_INFO_SYNC_CRON}")
    else:
        logger.info(f"美股基础信息同步已配置: {settings.US_BASIC_INFO_SYNC_CRON}")

    # 日线行情同步
    add_resilient_job(
        sched, run_us_daily_quotes_sync,
        CronTrigger.from_crontab(settings.US_DAILY_QUOTES_SYNC_CRON, timezone=tz),
        id="us_daily_quotes_sync",
        name="美股日线行情同步",
        kwargs={"incremental": True},
    )
    if not (settings.US_UNIFIED_ENABLED and settings.US_DAILY_QUOTES_SYNC_ENABLED):
        sched.pause_job("us_daily_quotes_sync")
        logger.info(f"美股日线行情同步已添加但暂停: {settings.US_DAILY_QUOTES_SYNC_CRON}")
    else:
        logger.info(f"美股日线行情同步已配置: {settings.US_DAILY_QUOTES_SYNC_CRON}")

    # 状态检查
    add_resilient_job(
        sched, run_us_status_check,
        CronTrigger.from_crontab(settings.US_STATUS_CHECK_CRON, timezone=tz),
        id="us_status_check",
        name="美股数据源状态检查",
    )
    if not (settings.US_UNIFIED_ENABLED and settings.US_STATUS_CHECK_ENABLED):
        sched.pause_job("us_status_check")
        logger.info(f"美股状态检查已添加但暂停: {settings.US_STATUS_CHECK_CRON}")
    else:
        logger.info(f"美股状态检查已配置: {settings.US_STATUS_CHECK_CRON}")


# ── A 股域级编排同步 ─────────────────────────────────────────────────

async def _run_cn_daily_sync():
    """A 股每日域级编排同步（交易日历检查 + 全市场增量）"""
    try:
        from app.worker.cn.cn_sync_orchestrator import get_cn_sync_orchestrator
        orchestrator = get_cn_sync_orchestrator()

        if not await orchestrator.is_trading_day():
            logger.info("今日非交易日，跳过域级编排同步")
            return

        logger.info("开始 A 股域级编排同步...")
        result = await orchestrator.run_full()
        success_count = sum(1 for r in result.values() if r.success)
        logger.info(
            "A 股域级编排同步完成: %d/%d 成功",
            success_count, len(result),
        )
    except Exception as e:
        logger.error(f"A 股域级编排同步失败: {e}", exc_info=True)


async def _run_cn_trade_calendar_sync():
    """交易日历同步（独立任务）"""
    try:
        from app.worker.cn.cn_sync_orchestrator import get_cn_sync_orchestrator
        orchestrator = get_cn_sync_orchestrator()
        sync = orchestrator._domain_syncs.get("trade_calendar")
        if sync:
            result = await sync.sync(providers={})
            logger.info("交易日历同步: success=%s, records=%d", result.success, result.records_synced)
    except Exception as e:
        logger.error(f"交易日历同步失败: {e}", exc_info=True)


async def _run_cn_aggregation_sync():
    """周线/月线聚合同步（日线完成后触发）"""
    try:
        from app.worker.cn.cn_sync_orchestrator import get_cn_sync_orchestrator
        from app.data.reader import check_freshness

        orchestrator = get_cn_sync_orchestrator()
        agg_sync = orchestrator._aggregation_sync

        # 获取自选股列表
        symbols = await orchestrator._get_all_symbols()
        if not symbols:
            logger.info("无股票数据，跳过聚合")
            return

        total = 0
        for symbol in symbols[:200]:  # 限制首次范围
            for period in ["weekly", "monthly"]:
                result = await agg_sync.sync(symbol=symbol, period=period)
                if result.success:
                    total += result.records_synced

        logger.info("聚合同步完成: %d 条记录", total)
    except Exception as e:
        logger.error(f"聚合同步失败: {e}", exc_info=True)


async def _run_cn_integrity_check():
    """A 股数据完整性检查"""
    try:
        from app.services.cn_data_integrity_service import get_integrity_service
        service = get_integrity_service()
        report = await service.run_full_check()
        logger.info(
            "完整性检查完成: errors=%d, warnings=%d",
            report.error_count, report.warning_count,
        )
    except Exception as e:
        logger.error(f"完整性检查失败: {e}", exc_info=True)


async def _run_cn_news_sync():
    """A 股新闻同步（自选股优先）"""
    try:
        from app.worker.cn.cn_sync_orchestrator import get_cn_sync_orchestrator
        orchestrator = get_cn_sync_orchestrator()
        result = await orchestrator.run_news_sync(favorites_only=True)
        logger.info(
            "新闻同步完成: success=%s, domains=%d, skipped=%s",
            result.success, len(result.domains), result.skipped,
        )
    except Exception as e:
        logger.error(f"新闻同步失败: {e}", exc_info=True)


def _register_cn_domain_jobs(sched: AsyncIOScheduler):
    """注册 A 股域级编排同步任务"""
    tz = settings.TIMEZONE

    # 每日全量同步（盘后 15:30）
    add_resilient_job(
        sched, _run_cn_daily_sync,
        CronTrigger(hour=15, minute=30, timezone=tz),
        id="cn_domain_daily_sync",
        name="A股域级编排同步（每日）",
    )
    logger.info("A股域级编排同步已配置: 每日 15:30")

    # 交易日历同步（每周一 06:00）
    add_resilient_job(
        sched, _run_cn_trade_calendar_sync,
        CronTrigger(day_of_week="mon", hour=6, minute=0, timezone=tz),
        id="cn_trade_calendar_sync",
        name="A股交易日历同步",
    )
    logger.info("A股交易日历同步已配置: 每周一 06:00")

    # 周线/月线聚合（盘后同步完成后 16:00）
    add_resilient_job(
        sched, _run_cn_aggregation_sync,
        CronTrigger(hour=16, minute=0, timezone=tz),
        id="cn_aggregation_sync",
        name="A股周线/月线聚合",
    )
    logger.info("A股聚合同步已配置: 每日 16:00")

    # 数据完整性检查（每日 17:00）
    add_resilient_job(
        sched, _run_cn_integrity_check,
        CronTrigger(hour=17, minute=0, timezone=tz),
        id="cn_integrity_check",
        name="A股数据完整性检查",
    )
    logger.info("A股完整性检查已配置: 每日 17:00")

    # 新闻同步（每日 12:00，仅自选股）
    add_resilient_job(
        sched, _run_cn_news_sync,
        CronTrigger(hour=12, minute=0, timezone=tz),
        id="cn_news_sync",
        name="A股新闻同步（自选股）",
    )
    logger.info("A股新闻同步已配置: 每日 12:00")
