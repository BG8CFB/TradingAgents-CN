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


# ── 数据源任务注册（每数据源一组）───────────────────────────────────────

def _register_tushare_jobs(sched: AsyncIOScheduler):
    """注册 Tushare 数据同步任务（5 个 job）"""
    from app.worker.cn import (
        run_tushare_basic_info_sync,
        run_tushare_quotes_sync,
        run_tushare_historical_sync,
        run_tushare_financial_sync,
        run_tushare_status_check,
    )

    tz = settings.TIMEZONE

    # 基础信息同步
    add_resilient_job(
        sched, run_tushare_basic_info_sync,
        CronTrigger.from_crontab(settings.TUSHARE_BASIC_INFO_SYNC_CRON, timezone=tz),
        id="tushare_basic_info_sync",
        name="股票基础信息同步（Tushare）",
        kwargs={"force_update": False},
    )
    if not (settings.TUSHARE_UNIFIED_ENABLED and settings.TUSHARE_BASIC_INFO_SYNC_ENABLED):
        sched.pause_job("tushare_basic_info_sync")
        logger.info(f"Tushare基础信息同步已添加但暂停: {settings.TUSHARE_BASIC_INFO_SYNC_CRON}")
    else:
        logger.info(f"Tushare基础信息同步已配置: {settings.TUSHARE_BASIC_INFO_SYNC_CRON}")

    # 实时行情同步
    add_resilient_job(
        sched, run_tushare_quotes_sync,
        CronTrigger.from_crontab(settings.TUSHARE_QUOTES_SYNC_CRON, timezone=tz),
        id="tushare_quotes_sync",
        name="实时行情同步（Tushare）",
    )
    if not (settings.TUSHARE_UNIFIED_ENABLED and settings.TUSHARE_QUOTES_SYNC_ENABLED):
        sched.pause_job("tushare_quotes_sync")
        logger.info(f"Tushare行情同步已添加但暂停: {settings.TUSHARE_QUOTES_SYNC_CRON}")
    else:
        logger.info(f"Tushare行情同步已配置: {settings.TUSHARE_QUOTES_SYNC_CRON}")

    # 历史数据同步
    add_resilient_job(
        sched, run_tushare_historical_sync,
        CronTrigger.from_crontab(settings.TUSHARE_HISTORICAL_SYNC_CRON, timezone=tz),
        id="tushare_historical_sync",
        name="历史数据同步（Tushare）",
        kwargs={"incremental": True},
    )
    if not (settings.TUSHARE_UNIFIED_ENABLED and settings.TUSHARE_HISTORICAL_SYNC_ENABLED):
        sched.pause_job("tushare_historical_sync")
        logger.info(f"Tushare历史数据同步已添加但暂停: {settings.TUSHARE_HISTORICAL_SYNC_CRON}")
    else:
        logger.info(f"Tushare历史数据同步已配置: {settings.TUSHARE_HISTORICAL_SYNC_CRON}")

    # 财务数据同步
    add_resilient_job(
        sched, run_tushare_financial_sync,
        CronTrigger.from_crontab(settings.TUSHARE_FINANCIAL_SYNC_CRON, timezone=tz),
        id="tushare_financial_sync",
        name="财务数据同步（Tushare）",
    )
    if not (settings.TUSHARE_UNIFIED_ENABLED and settings.TUSHARE_FINANCIAL_SYNC_ENABLED):
        sched.pause_job("tushare_financial_sync")
        logger.info(f"Tushare财务数据同步已添加但暂停: {settings.TUSHARE_FINANCIAL_SYNC_CRON}")
    else:
        logger.info(f"Tushare财务数据同步已配置: {settings.TUSHARE_FINANCIAL_SYNC_CRON}")

    # 状态检查
    add_resilient_job(
        sched, run_tushare_status_check,
        CronTrigger.from_crontab(settings.TUSHARE_STATUS_CHECK_CRON, timezone=tz),
        id="tushare_status_check",
        name="数据源状态检查（Tushare）",
    )
    if not (settings.TUSHARE_UNIFIED_ENABLED and settings.TUSHARE_STATUS_CHECK_ENABLED):
        sched.pause_job("tushare_status_check")
        logger.info(f"Tushare状态检查已添加但暂停: {settings.TUSHARE_STATUS_CHECK_CRON}")
    else:
        logger.info(f"Tushare状态检查已配置: {settings.TUSHARE_STATUS_CHECK_CRON}")


def _register_akshare_jobs(sched: AsyncIOScheduler):
    """注册 AKShare 数据同步任务（5 个 job）"""
    from app.worker.cn import (
        run_akshare_basic_info_sync,
        run_akshare_quotes_sync,
        run_akshare_historical_sync,
        run_akshare_financial_sync,
        run_akshare_status_check,
    )

    tz = settings.TIMEZONE

    # 基础信息同步
    add_resilient_job(
        sched, run_akshare_basic_info_sync,
        CronTrigger.from_crontab(settings.AKSHARE_BASIC_INFO_SYNC_CRON, timezone=tz),
        id="akshare_basic_info_sync",
        name="股票基础信息同步（AKShare）",
        kwargs={"force_update": False},
    )
    if not (settings.AKSHARE_UNIFIED_ENABLED and settings.AKSHARE_BASIC_INFO_SYNC_ENABLED):
        sched.pause_job("akshare_basic_info_sync")
        logger.info(f"AKShare基础信息同步已添加但暂停: {settings.AKSHARE_BASIC_INFO_SYNC_CRON}")
    else:
        logger.info(f"AKShare基础信息同步已配置: {settings.AKSHARE_BASIC_INFO_SYNC_CRON}")

    # 实时行情同步
    add_resilient_job(
        sched, run_akshare_quotes_sync,
        CronTrigger.from_crontab(settings.AKSHARE_QUOTES_SYNC_CRON, timezone=tz),
        id="akshare_quotes_sync",
        name="实时行情同步（AKShare）",
    )
    if not (settings.AKSHARE_UNIFIED_ENABLED and settings.AKSHARE_QUOTES_SYNC_ENABLED):
        sched.pause_job("akshare_quotes_sync")
        logger.info(f"AKShare行情同步已添加但暂停: {settings.AKSHARE_QUOTES_SYNC_CRON}")
    else:
        logger.info(f"AKShare行情同步已配置: {settings.AKSHARE_QUOTES_SYNC_CRON}")

    # 历史数据同步
    add_resilient_job(
        sched, run_akshare_historical_sync,
        CronTrigger.from_crontab(settings.AKSHARE_HISTORICAL_SYNC_CRON, timezone=tz),
        id="akshare_historical_sync",
        name="历史数据同步（AKShare）",
        kwargs={"incremental": True},
    )
    if not (settings.AKSHARE_UNIFIED_ENABLED and settings.AKSHARE_HISTORICAL_SYNC_ENABLED):
        sched.pause_job("akshare_historical_sync")
        logger.info(f"AKShare历史数据同步已添加但暂停: {settings.AKSHARE_HISTORICAL_SYNC_CRON}")
    else:
        logger.info(f"AKShare历史数据同步已配置: {settings.AKSHARE_HISTORICAL_SYNC_CRON}")

    # 财务数据同步
    add_resilient_job(
        sched, run_akshare_financial_sync,
        CronTrigger.from_crontab(settings.AKSHARE_FINANCIAL_SYNC_CRON, timezone=tz),
        id="akshare_financial_sync",
        name="财务数据同步（AKShare）",
    )
    if not (settings.AKSHARE_UNIFIED_ENABLED and settings.AKSHARE_FINANCIAL_SYNC_ENABLED):
        sched.pause_job("akshare_financial_sync")
        logger.info(f"AKShare财务数据同步已添加但暂停: {settings.AKSHARE_FINANCIAL_SYNC_CRON}")
    else:
        logger.info(f"AKShare财务数据同步已配置: {settings.AKSHARE_FINANCIAL_SYNC_CRON}")

    # 状态检查
    add_resilient_job(
        sched, run_akshare_status_check,
        CronTrigger.from_crontab(settings.AKSHARE_STATUS_CHECK_CRON, timezone=tz),
        id="akshare_status_check",
        name="数据源状态检查（AKShare）",
    )
    if not (settings.AKSHARE_UNIFIED_ENABLED and settings.AKSHARE_STATUS_CHECK_ENABLED):
        sched.pause_job("akshare_status_check")
        logger.info(f"AKShare状态检查已添加但暂停: {settings.AKSHARE_STATUS_CHECK_CRON}")
    else:
        logger.info(f"AKShare状态检查已配置: {settings.AKSHARE_STATUS_CHECK_CRON}")


def _register_baostock_jobs(sched: AsyncIOScheduler):
    """注册 BaoStock 数据同步任务（4 个 job，BaoStock 不支持实时行情）"""
    from app.worker.cn import (
        run_baostock_basic_info_sync,
        run_baostock_daily_quotes_sync,
        run_baostock_historical_sync,
        run_baostock_status_check,
    )

    tz = settings.TIMEZONE

    # 基础信息同步
    add_resilient_job(
        sched, run_baostock_basic_info_sync,
        CronTrigger.from_crontab(settings.BAOSTOCK_BASIC_INFO_SYNC_CRON, timezone=tz),
        id="baostock_basic_info_sync",
        name="股票基础信息同步（BaoStock）",
    )
    if not (settings.BAOSTOCK_UNIFIED_ENABLED and settings.BAOSTOCK_BASIC_INFO_SYNC_ENABLED):
        sched.pause_job("baostock_basic_info_sync")
        logger.info(f"BaoStock基础信息同步已添加但暂停: {settings.BAOSTOCK_BASIC_INFO_SYNC_CRON}")
    else:
        logger.info(f"BaoStock基础信息同步已配置: {settings.BAOSTOCK_BASIC_INFO_SYNC_CRON}")

    # 日K线同步（注意：BaoStock不支持实时行情）
    add_resilient_job(
        sched, run_baostock_daily_quotes_sync,
        CronTrigger.from_crontab(settings.BAOSTOCK_DAILY_QUOTES_SYNC_CRON, timezone=tz),
        id="baostock_daily_quotes_sync",
        name="日K线数据同步（BaoStock）",
    )
    if not (settings.BAOSTOCK_UNIFIED_ENABLED and settings.BAOSTOCK_DAILY_QUOTES_SYNC_ENABLED):
        sched.pause_job("baostock_daily_quotes_sync")
        logger.info(f"BaoStock日K线同步已添加但暂停: {settings.BAOSTOCK_DAILY_QUOTES_SYNC_CRON}")
    else:
        logger.info(f"BaoStock日K线同步已配置: {settings.BAOSTOCK_DAILY_QUOTES_SYNC_CRON} (注意：BaoStock不支持实时行情)")

    # 历史数据同步
    add_resilient_job(
        sched, run_baostock_historical_sync,
        CronTrigger.from_crontab(settings.BAOSTOCK_HISTORICAL_SYNC_CRON, timezone=tz),
        id="baostock_historical_sync",
        name="历史数据同步（BaoStock）",
    )
    if not (settings.BAOSTOCK_UNIFIED_ENABLED and settings.BAOSTOCK_HISTORICAL_SYNC_ENABLED):
        sched.pause_job("baostock_historical_sync")
        logger.info(f"BaoStock历史数据同步已添加但暂停: {settings.BAOSTOCK_HISTORICAL_SYNC_CRON}")
    else:
        logger.info(f"BaoStock历史数据同步已配置: {settings.BAOSTOCK_HISTORICAL_SYNC_CRON}")

    # 状态检查
    add_resilient_job(
        sched, run_baostock_status_check,
        CronTrigger.from_crontab(settings.BAOSTOCK_STATUS_CHECK_CRON, timezone=tz),
        id="baostock_status_check",
        name="数据源状态检查（BaoStock）",
    )
    if not (settings.BAOSTOCK_UNIFIED_ENABLED and settings.BAOSTOCK_STATUS_CHECK_ENABLED):
        sched.pause_job("baostock_status_check")
        logger.info(f"BaoStock状态检查已添加但暂停: {settings.BAOSTOCK_STATUS_CHECK_CRON}")
    else:
        logger.info(f"BaoStock状态检查已配置: {settings.BAOSTOCK_STATUS_CHECK_CRON}")


# ── 新闻同步任务 ──────────────────────────────────────────────────────

async def _make_news_sync_func():
    """创建新闻同步闭包（延迟绑定 AKShare sync service）"""
    from app.worker.cn import get_akshare_sync_service

    async def run_news_sync():
        """运行新闻同步任务 - 使用AKShare同步自选股新闻"""
        try:
            logger.info("开始新闻数据同步（AKShare - 仅自选股）...")
            service = await get_akshare_sync_service()
            result = await service.sync_news_data(
                symbols=None,
                max_news_per_stock=settings.NEWS_SYNC_MAX_PER_SOURCE,
                favorites_only=True,
            )
            logger.info(
                f"新闻同步完成: "
                f"处理{result['total_processed']}只自选股, "
                f"成功{result['success_count']}只, "
                f"失败{result['error_count']}只, "
                f"新闻总数{result['news_count']}条, "
                f"耗时{(now_utc() - result['start_time']).total_seconds():.2f}秒"
            )
        except Exception as e:
            logger.error(f"新闻同步失败: {e}", exc_info=True)

    return run_news_sync


def _register_news_job(sched: AsyncIOScheduler, run_news_sync):
    """注册新闻同步任务"""
    tz = settings.TIMEZONE

    add_resilient_job(
        sched, run_news_sync,
        CronTrigger.from_crontab(settings.NEWS_SYNC_CRON, timezone=tz),
        id="news_sync",
        name="新闻数据同步（AKShare - 仅自选股）",
    )
    if not settings.NEWS_SYNC_ENABLED:
        sched.pause_job("news_sync")
        logger.info(f"新闻数据同步已添加但暂停: {settings.NEWS_SYNC_CRON}")
    else:
        logger.info(f"新闻数据同步已配置（仅自选股）: {settings.NEWS_SYNC_CRON}")


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

    # ── 各数据源同步任务 ──────────────────────────────────────────────
    logger.info("配置Tushare统一数据同步任务...")
    _register_tushare_jobs(scheduler)

    logger.info("配置AKShare统一数据同步任务...")
    _register_akshare_jobs(scheduler)

    logger.info("配置BaoStock统一数据同步任务...")
    _register_baostock_jobs(scheduler)

    # ── 新闻同步 ──────────────────────────────────────────────────────
    logger.info("配置新闻数据同步任务...")
    run_news_sync = await _make_news_sync_func()
    _register_news_job(scheduler, run_news_sync)

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
