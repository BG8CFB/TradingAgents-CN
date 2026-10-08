"""Screening consumers shared by both scheduler entry points.

Registration never runs a job or an LLM. The scheduled job reads the existing
factor batch; optional paid insights retain their explicit, default-off setting.
"""

import logging

from apscheduler.triggers.cron import CronTrigger

from app.core.config import settings

logger = logging.getLogger(__name__)
JOB_ID = "screening_daily_recommendations"


def register_screening_jobs(scheduler):
    scheduler.add_job(
        run_screening_daily_recommendations,
        CronTrigger(hour=20, minute=47, timezone=settings.TIMEZONE),
        id=JOB_ID,
        name="选股每日推荐生成",
        max_instances=1,
        misfire_grace_time=600,
        coalesce=True,
        replace_existing=True,
    )
    logger.info("选股每日推荐任务已注册: 每日 20:47（按已有因子交易日幂等生成）")


async def run_screening_daily_recommendations():
    from app.services.screening.strategy_service import StrategyService

    try:
        summary = await StrategyService().generate_daily_recommendations()
    except Exception:
        logger.error("选股每日推荐生成失败", exc_info=True)
        raise
    if summary["strategies_failed"]:
        raise RuntimeError(
            f"选股每日推荐 {summary['strategies_failed']} 个策略生成失败；"
            f"已保留 {summary['strategies_written']} 个成功模板"
        )
    if not summary["strategies_written"]:
        logger.warning("选股每日推荐未生成: %s", summary)
        return summary
    logger.info("选股每日推荐完成: %s", summary)

    # Default-off check precedes any model client construction or request.
    from app.services.screening.insight_service import ScreeningInsightService

    try:
        summary["insight"] = await ScreeningInsightService().run_daily_auto_if_enabled()
    except Exception:
        logger.error("每日自动研判异常", exc_info=True)
    return summary
