"""QMT tick 保留期清理任务（PRD FR-06 规则 3 / DD-03）。

设计取舍（技术方案 DD-03）：**不用 Mongo TTL 索引**——
① 时间字段是字符串（`trade_date`），TTL 索引要求 BSON Date，需额外加
   `expires_at` 字段；
② TTL 删除**不产生任何审计记录**，而 PRD FR-06 要求清理动作可审计。
故改为每日定时 Job：按 `trade_date` 分区删除 + 写 `sync_events`。

体量背景（PRD RK-07）：全市场 tick 日增估算 10~50 GB，保留期默认 60 天。
清理失败不得影响采集主流程（失败只告警，不抛给调度器）。
"""

import logging
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

from app.core.config import settings
from app.utils.timezone import now_utc

logger = logging.getLogger("worker.qmt")

_DOMAIN = "tick_quotes"
_MARKET = "CN"


def _resolve_retention_days(explicit: Optional[int] = None) -> int:
    """保留天数：显式入参 → Web UI 配置（Mongo）→ ENV/Settings → 默认 60。"""
    if explicit is not None:
        return max(1, int(explicit))
    try:
        from app.data.sources.cn.qmt.config import get_qmt_tick_retention_days

        configured = get_qmt_tick_retention_days()
        if configured is not None:
            return max(1, int(configured))
    except Exception as e:  # noqa: BLE001 — 配置不可读时退回 Settings
        logger.debug("读取 tick 保留期配置失败（回退 Settings）: %s", e)
    return max(1, int(settings.QMT_TICK_RETENTION_DAYS))


def _cutoff_date(retention_days: int, today: Optional[datetime] = None) -> str:
    """保留期截止日（'YYYY-MM-DD'）：`trade_date < cutoff` 的记录被清理。

    用自然日而非交易日：保留期是存储策略（磁盘容量），不是数据完整性约束；
    交易日口径需查日历，且对「刚好 60 天内」的边界没有业务意义。
    """
    base = today or datetime.now()
    return (base - timedelta(days=retention_days)).strftime("%Y-%m-%d")


async def _write_cleanup_event(
    *, deleted: int, cutoff: str, retention_days: int,
    success: bool, error: Optional[str], duration_ms: int,
) -> None:
    """写 sync_events 审计记录（失败不阻断清理流程）。"""
    try:
        from app.data.storage.mongo.client import get_motor_db
        from app.data.storage.mongo.collections import get_collection_name

        db = get_motor_db()
        await db[get_collection_name("sync_events", _MARKET)].insert_one({
            "event_type": "SYNC_SUCCESS" if success else "SYNC_FAILED",
            "domain": _DOMAIN,
            "source": "qmt",
            "market": _MARKET,
            "symbol": None,
            "record_count": deleted,
            "duration_ms": duration_ms,
            "error_message": error,
            # 清理动作的审计溯源字段
            "data_source": "qmt_tick_cleanup",
            "retention_days": retention_days,
            "cutoff_date": cutoff,
            "updated_at": now_utc().isoformat(),
        })
    except Exception as e:  # noqa: BLE001 — 审计写失败不阻断清理
        logger.debug("tick 清理事件写入失败（忽略）: %s", e)


async def cleanup_qmt_tick(retention_days: Optional[int] = None) -> Dict[str, Any]:
    """清理超出保留期的 tick 分区（调度注册与手动触发共用）。

    Args:
        retention_days: 保留天数；None 时按 Web UI → ENV → 默认 60 解析。

    Returns:
        ``{"success", "deleted", "cutoff_date", "retention_days",
        "duration_ms", "error"}``
    """
    import time

    start = time.time()
    days = _resolve_retention_days(retention_days)
    cutoff = _cutoff_date(days)

    if not settings.QMT_ENABLED:
        # 源关闭时不清理：既有 qmt 数据保留无害（PRD 10.4 回滚口径）
        return {
            "success": False, "skipped": True,
            "reason": "QMT_ENABLED=false", "retention_days": days,
            "cutoff_date": cutoff, "deleted": 0,
        }

    try:
        from app.data.storage.mongo.repositories.tick_quotes_repo import (
            TickQuotesRepo,
        )

        deleted = await TickQuotesRepo().delete_before_date(_MARKET, cutoff)
    except Exception as e:  # noqa: BLE001
        elapsed = int((time.time() - start) * 1000)
        logger.error(
            "QMT tick 保留期清理失败（cutoff=%s, 保留 %d 天）: %s",
            cutoff, days, e, exc_info=True,
        )
        await _write_cleanup_event(
            deleted=0, cutoff=cutoff, retention_days=days,
            success=False, error=str(e), duration_ms=elapsed,
        )
        return {
            "success": False, "deleted": 0, "cutoff_date": cutoff,
            "retention_days": days, "duration_ms": elapsed, "error": str(e),
        }

    elapsed = int((time.time() - start) * 1000)
    logger.info(
        "QMT tick 保留期清理完成: 删除 %d 条（trade_date < %s，保留 %d 天，%dms）",
        deleted, cutoff, days, elapsed,
    )
    await _write_cleanup_event(
        deleted=deleted, cutoff=cutoff, retention_days=days,
        success=True, error=None, duration_ms=elapsed,
    )
    return {
        "success": True, "deleted": deleted, "cutoff_date": cutoff,
        "retention_days": days, "duration_ms": elapsed, "error": None,
    }
