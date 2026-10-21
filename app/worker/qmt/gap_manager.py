"""增量缺口管理（PRD FR-12）。

三步闭环：**检测 → 登记 → 补采**。

- 检测口径：以**库内交易日历**（`trade_calendar` 域，权威）为基准，逐交易日
  检查目标域在库内是否有该日分区（存在性计数，走 `trade_date` 索引）。
  不用 datadir 日历 —— 那正是可能缺数据的一方，用它当基准会把缺口"检测成正常"。
- 补采顺序：**先 qmt（读历史 datadir 分区），缺失则转既有源兜底**（FR-12 规则 1）。
- 防抖：同一缺口每轮失败计数 +1，达 ``QMT_GAP_MAX_ATTEMPTS``（默认 3）转
  `abandoned` 并告警，不再自动补（FR-12 规则 2 / 附录 A「补采连续 3 轮失败」）。

已知边界（本版本刻意不做，避免假装支持）：
- 分时/tick 的**既有源兜底**未实现：tushare/akshare 的分时接口是按股票拉取，
  全市场逐票兜底属于独立工作量（PRD T-3 待核对 `intraday_quotes` 字段覆盖度）。
  这两域在 qmt 分区缺失时记 `fallback_unsupported` 并累积轮次，最终告警转人工。
- 分区级判定：某日只要**有任一记录**即视为非缺口，不校验全市场覆盖率
  （覆盖率口径由 tick 自检 / domain_health 负责，避免两套语义打架）。
"""

import logging
import time
from typing import Any, Dict, List, Optional

from app.core.config import settings
from app.utils.timezone import now_utc

logger = logging.getLogger("worker.qmt")

_MARKET = "CN"
_EXCHANGE = "SSE"

# 缺口检测覆盖的域（FR-12：日线/分时/tick）
GAP_DOMAINS = ("daily_quotes", "intraday_quotes", "tick_quotes")

# 分时兜底未实现（见模块注释）
_NO_FALLBACK_DOMAINS = frozenset({"intraday_quotes", "tick_quotes"})


def _presence_query(domain: str, day: str) -> Dict[str, Any]:
    """按域的「该日是否有分区」查询条件。

    ``intraday_quotes`` 的日期字段是 ``datetime``（'YYYY-MM-DD HH:MM:SS'），
    只能区间匹配；其余域是 ``trade_date``（'YYYY-MM-DD'）可精确匹配。
    """
    if domain == "intraday_quotes":
        return {"datetime": {"$gte": f"{day} 00:00:00", "$lte": f"{day} 23:59:59"}}
    return {"trade_date": day}


async def expected_trade_dates(lookback_days: int) -> List[str]:
    """最近 N 个交易日（'YYYY-MM-DD' 升序）——以库内交易日历为基准。

    日历缺失返回空列表：无基准就不做缺口判定，避免把每个日期都误判成缺口。
    """
    from app.data.storage.mongo.repositories.trade_calendar_repo import (
        TradeCalendarRepo,
    )

    dates = await TradeCalendarRepo().get_range(
        _EXCHANGE, _MARKET, "1990-01-01", "2099-12-31"
    )
    open_days = [d["cal_date"] for d in dates if d.get("is_open")]
    if not open_days:
        logger.warning("缺口检测跳过：库内交易日历为空（先跑 trade_calendar 同步）")
        return []
    return sorted(open_days)[-max(1, int(lookback_days)):]


async def has_partition(market: str, domain: str, day: str) -> bool:
    """该日是否已有分区（存在性计数；只读，不取业务数据）。"""
    from app.data.storage.mongo.client import get_motor_db
    from app.data.storage.mongo.collections import get_collection_name

    db = get_motor_db()
    coll = db[get_collection_name(domain, market)]
    return bool(await coll.count_documents(_presence_query(domain, day)))


async def detect_and_register(
    lookback_days: Optional[int] = None,
    domains: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """检测缺口并登记（幂等：已登记的缺口不重置轮次）。

    Returns:
        ``{"dates": [...], "registered": {domain: [dates]}, "existing": int}``
    """
    from app.data.storage.mongo.repositories.data_gap_repo import DataGapRepo

    days = await expected_trade_dates(
        lookback_days if lookback_days is not None
        else settings.QMT_GAP_LOOKBACK_DAYS
    )
    result: Dict[str, Any] = {
        "dates": days, "registered": {}, "existing": 0, "checked": len(days),
    }
    if not days:
        return result

    repo = DataGapRepo()
    for domain in (domains or list(GAP_DOMAINS)):
        new_dates: List[str] = []
        for day in days:
            if await has_partition(_MARKET, domain, day):
                continue
            created = await repo.register(
                _MARKET, domain, day, reason="partition_missing"
            )
            if created:
                new_dates.append(day)
            else:
                result["existing"] += 1
        if new_dates:
            result["registered"][domain] = new_dates
    return result


async def _fill_by_qmt(market: str, domain: str, day: str) -> Dict[str, Any]:
    """qmt 优先补采（读历史 datadir 分区）。"""
    from app.worker.qmt.jobs import (
        QmtDailyQuotesSync,
        QmtIntradayQuotesSync,
        _parse_intraday_freqs,
    )

    if domain == "daily_quotes":
        return await QmtDailyQuotesSync().sync(
            "get_daily_quotes_batch_range",
            lambda: {"start_date": day, "end_date": day},
        )

    if domain == "intraday_quotes":
        freqs = _parse_intraday_freqs(settings.QMT_INTRADAY_FREQS)
        outcomes = []
        for freq in freqs:
            outcomes.append(
                await QmtIntradayQuotesSync().sync(
                    "get_intraday_quotes_batch_range",
                    lambda freq=freq: {
                        "start_date": day, "end_date": day, "freq": freq,
                    },
                )
            )
        ok = [o for o in outcomes if o.get("success")]
        return {
            "domain": domain,
            "success": bool(ok),
            "error": None if ok else "qmt_intraday_empty",
        }

    if domain == "tick_quotes":
        from app.worker.qmt.tick_collect import collect_tick

        summary = await collect_tick(day)
        summary["domain"] = domain
        return summary

    return {"domain": domain, "success": False, "error": "unsupported_domain"}


async def _fill_by_fallback(market: str, domain: str, day: str) -> Dict[str, Any]:
    """既有源兜底补采（FR-12 规则 1 后半段）。

    只在 `daily_quotes` 上实现：既有源的批量日线接口（``get_daily_quotes_batch``）
    与平台基类同构，换链即可复用。分时/tick 见模块注释的已知边界。
    """
    if domain in _NO_FALLBACK_DOMAINS:
        return {
            "domain": domain, "success": False,
            "error": "fallback_unsupported（既有源按标的拉取，全市场兜底未实现）",
        }
    if domain != "daily_quotes":
        return {"domain": domain, "success": False, "error": "unsupported_domain"}

    from app.worker.base_market_sync import BaseMarketDomainSync

    class _NonQmtSync(BaseMarketDomainSync):
        """排除 qmt 的兜底链（qmt 已在上一级尝试过）。"""

        market = _MARKET
        domain = "daily_quotes"
        description = "缺口补采（既有源兜底）"

        async def get_sources(self) -> List[str]:
            chain = await super().get_sources()
            return [s for s in chain if s != "qmt"]

    return await _NonQmtSync().sync(
        "get_daily_quotes_batch", lambda: {"trade_date": day}
    )


async def _write_gap_event(
    action: str, payload: Dict[str, Any], *, success: bool,
) -> None:
    """缺口生命周期审计（PRD 附录 B `qmt_gap_registered` 等埋点）。"""
    try:
        from app.data.storage.mongo.client import get_motor_db
        from app.data.storage.mongo.collections import get_collection_name

        db = get_motor_db()
        doc = {
            "event_type": "SYNC_SUCCESS" if success else "SYNC_FAILED",
            "domain": payload.get("domain"),
            "source": "qmt",
            "market": _MARKET,
            "symbol": None,
            "record_count": int(payload.get("written_rows") or 0),
            "duration_ms": 0,
            "error_message": payload.get("error"),
            "data_source": "qmt_gap",
            "action": action,
            "gap_date": payload.get("gap_date"),
            "attempts": payload.get("attempts"),
            "updated_at": now_utc().isoformat(),
        }
        await db[get_collection_name("sync_events", _MARKET)].insert_one(doc)
    except Exception as e:  # noqa: BLE001 — 审计写失败不影响补采
        logger.debug("缺口事件写入失败（忽略）: %s", e)


async def run_gap_fill(
    max_attempts: Optional[int] = None,
    domains: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """补采入口：检测登记 → 逐缺口补采 → 记轮次/告警。

    Args:
        max_attempts: 单缺口轮次上限；None → ``settings.QMT_GAP_MAX_ATTEMPTS``。
        domains: 只处理指定域（运维定向补采 / 测试隔离）；None → 全部 ``GAP_DOMAINS``。

    调度语义：每日一次的兜底任务，`max_instances=1`（不并发，避免同一缺口
    被多个实例同时补采而重复累加轮次）。
    """
    start = time.time()
    attempts_cap = int(
        max_attempts if max_attempts is not None
        else settings.QMT_GAP_MAX_ATTEMPTS
    )
    scope = list(domains) if domains else list(GAP_DOMAINS)

    summary: Dict[str, Any] = {
        "success": False,
        "detected": {},
        "filled": [],
        "abandoned": [],
        "still_open": 0,
        "duration_ms": 0,
    }
    if not settings.QMT_ENABLED or not settings.QMT_GAP_ENABLED:
        summary["skipped"] = True
        summary["reason"] = (
            "QMT_ENABLED=false" if not settings.QMT_ENABLED
            else "QMT_GAP_ENABLED=false"
        )
        return summary

    from app.data.storage.mongo.repositories.data_gap_repo import DataGapRepo

    detection = await detect_and_register(domains=scope)
    summary["detected"] = detection.get("registered", {})
    if detection.get("registered"):
        await _write_gap_event(
            "registered",
            {
                "domain": ",".join(detection["registered"].keys()),
                "error": None,
                "attempts": 0,
            },
            success=True,
        )

    repo = DataGapRepo()
    gaps = [
        g for g in await repo.open_gaps(_MARKET)
        if g.get("domain") in scope
    ]
    qmt_available = bool(settings.QMT_ENABLED)

    for gap in gaps:
        domain, day = gap["domain"], gap["gap_date"]
        # 已被其他轮次补齐（例如既有源夜跑刚写完）→ 直接消除登记
        if await has_partition(_MARKET, domain, day):
            await repo.mark_filled(_MARKET, domain, day, "preexisting")
            summary["filled"].append({"domain": domain, "gap_date": day,
                                      "source": "preexisting"})
            await _write_gap_event(
                "filled",
                {"domain": domain, "gap_date": day, "error": None,
                 "attempts": int(gap.get("attempts") or 0)},
                success=True,
            )
            continue

        outcome: Dict[str, Any] = {"success": False,
                                   "error": "qmt_disabled"}
        if qmt_available:
            outcome = await _fill_by_qmt(_MARKET, domain, day)
        if not outcome.get("success"):
            fallback = await _fill_by_fallback(_MARKET, domain, day)
            if fallback.get("success"):
                outcome = fallback

        if outcome.get("success"):
            await repo.mark_filled(_MARKET, domain, day, "qmt")
            summary["filled"].append(
                {"domain": domain, "gap_date": day, "source": "qmt"}
            )
            await _write_gap_event(
                "filled",
                {"domain": domain, "gap_date": day, "error": None,
                 "written_rows": outcome.get("record_count") or 0},
                success=True,
            )
            continue

        bumped = await repo.bump_attempt(
            _MARKET, domain, day,
            str(outcome.get("error") or "unknown"),
            attempts_cap,
        )
        if bumped["abandoned"]:
            summary["abandoned"].append(
                {"domain": domain, "gap_date": day,
                 "attempts": bumped["attempts"],
                 "error": outcome.get("error")}
            )
            logger.error(
                "缺口补采连续 %d 轮失败，停止自动补采转人工: %s %s（%s）",
                bumped["attempts"], domain, day, outcome.get("error"),
            )
        else:
            summary["still_open"] += 1
            logger.warning(
                "缺口补采失败（第 %d/%d 轮）: %s %s（%s）",
                bumped["attempts"], attempts_cap, domain, day,
                outcome.get("error"),
            )
        await _write_gap_event(
            "fill_failed",
            {"domain": domain, "gap_date": day,
             "error": outcome.get("error"), "attempts": bumped["attempts"]},
            success=False,
        )

    elapsed = int((time.time() - start) * 1000)
    summary["duration_ms"] = elapsed
    summary["success"] = not summary["abandoned"]
    logger.info(
        "缺口管理完成: 新登记 %s，补齐 %d，放弃 %d，待补 %d，%dms",
        {k: len(v) for k, v in summary["detected"].items()},
        len(summary["filled"]), len(summary["abandoned"]),
        summary["still_open"], elapsed,
    )
    return summary
