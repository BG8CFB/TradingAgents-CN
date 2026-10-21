"""QMT tick 流式采集（M2 / PRD FR-06）。

为什么不用 ``BaseMarketDomainSync``：
该基类的语义是「一次 fetch → 全量 normalize → 全量 validate → upsert」，
而 tick 单日全市场可达千万级记录（PRD RK-07 估算 10~50 GB/日），一次性
materialize 必然打满内存。本模块改为**逐票流式**：小批并发读取 → 标准化 →
校验 → 入库 → 释放，峰值内存只与批大小相关。

同时承接 FR-06 的两条强制性规则：
- 规则 4：每日采集后覆盖率自检 ≥95%，不足登记缺口（写 sync_events）；
- 规则 5：日写入量超 ``QMT_TICK_DAILY_LIMIT`` **自动暂停 tick 采集并告警**，
  其余域不受影响（本模块只停自己，不抛异常给上层 job）。
"""

import asyncio
import logging
import time
from typing import Any, Dict, List, Optional

from app.core.config import settings

logger = logging.getLogger("worker.qmt")

_MARKET = "CN"
_DOMAIN = "tick_quotes"

# 覆盖率自检门槛（PRD 3.2「tick 自检覆盖率 ≥ 95%」）
TICK_COVERAGE_THRESHOLD = 0.95


def _ymd(iso_date: str) -> str:
    """'YYYY-MM-DD' → 'YYYYMMDD'（reader 的 trade_date 口径）。"""
    return str(iso_date).replace("-", "")


async def _write_event(
    *,
    event_type: str,
    data_source: str,
    record_count: int,
    duration_ms: int,
    error: Optional[str] = None,
    extra: Optional[Dict[str, Any]] = None,
) -> None:
    """写 sync_events（审计；失败不阻断采集）。"""
    try:
        from app.data.storage.mongo.client import get_motor_db
        from app.data.storage.mongo.collections import get_collection_name
        from app.utils.timezone import now_utc

        doc = {
            "event_type": event_type,
            "domain": _DOMAIN,
            "source": "qmt",
            "market": _MARKET,
            "symbol": None,
            "record_count": record_count,
            "duration_ms": duration_ms,
            "error_message": error,
            "data_source": data_source,
            "updated_at": now_utc().isoformat(),
        }
        if extra:
            doc.update(extra)
        db = get_motor_db()
        await db[get_collection_name("sync_events", _MARKET)].insert_one(doc)
    except Exception as e:  # noqa: BLE001 — 审计写失败不影响采集
        logger.debug("tick 采集事件写入失败（忽略）: %s", e)


async def collect_tick(
    trade_date: str,
    *,
    daily_limit: Optional[int] = None,
    coverage_threshold: float = TICK_COVERAGE_THRESHOLD,
) -> Dict[str, Any]:
    """采集单日全市场 tick 并入库（流式，受日写入量阈值约束）。

    Args:
        trade_date: 'YYYY-MM-DD'。
        daily_limit: 单日写入行数阈值；None → ``settings.QMT_TICK_DAILY_LIMIT``。
        coverage_threshold: 覆盖率告警门槛（默认 0.95）。

    Returns:
        ``{"success", "trade_date", "written_rows", "contracts_total",
        "contracts_with_data", "coverage_ratio", "paused_by_limit",
        "failed_contracts", "duration_ms"}``
    """
    start = time.time()
    limit = int(
        daily_limit if daily_limit is not None
        else settings.QMT_TICK_DAILY_LIMIT
    )

    summary: Dict[str, Any] = {
        "success": False,
        "trade_date": trade_date,
        "written_rows": 0,
        "contracts_total": 0,
        "contracts_with_data": 0,
        "coverage_ratio": 0.0,
        "paused_by_limit": False,
        "failed_contracts": 0,
        "duration_ms": 0,
    }

    if not settings.QMT_ENABLED:
        summary["reason"] = "QMT_ENABLED=false"
        return summary

    from app.data.processor.normalizer import Normalizer
    from app.data.processor.validator import Validator
    from app.data.sources.cn.qmt.adapter import QmtAdapter
    from app.data.sources.cn.qmt.provider import QmtProvider
    from app.data.storage.mongo.repositories.tick_quotes_repo import TickQuotesRepo

    provider = QmtProvider()
    adapter = QmtAdapter(provider=provider)
    normalizer = Normalizer()
    validator = Validator()
    repo = TickQuotesRepo()

    universe = await provider.get_stock_list()
    codes: List[str] = (
        list(universe["ts_code"]) if "ts_code" in getattr(universe, "columns", [])
        else []
    )
    if not codes:
        summary["reason"] = "universe_empty"
        logger.warning("QMT tick 采集: 合约列表为空，跳过 %s", trade_date)
        return summary
    summary["contracts_total"] = len(codes)

    ymd = _ymd(trade_date)
    # 批大小跟随解析并发：每批读完立即入库并释放，峰值内存与批大小成正比
    batch_size = max(1, int(settings.QMT_READ_WORKERS) * 2)

    written = 0
    with_data = 0
    failed = 0
    paused = False

    for offset in range(0, len(codes), batch_size):
        batch = codes[offset: offset + batch_size]
        frames = await asyncio.gather(
            *[provider.read_tick_one(code, ymd) for code in batch],
            return_exceptions=True,
        )

        docs: List[Dict] = []
        for res in frames:
            if isinstance(res, BaseException):
                failed += 1
                continue
            if res is None or getattr(res, "empty", True):
                continue
            result = normalizer.normalize_with_status(res, _DOMAIN, adapter)
            if not result.records:
                continue
            valid, _errors = validator.validate(result.records, _DOMAIN, _MARKET)
            if valid:
                with_data += 1
                docs.extend(valid)

        if docs:
            written += await repo.upsert_many(docs, _MARKET)

        # 阈值检查在**批边界**执行：一批之内最多超出一个批大小的行数，
        # 避免出现「已写 5000 万行才发现超限」的内存堆积。
        if written >= limit:
            paused = True
            logger.error(
                "QMT tick 写入量达阈值 %d（已写 %d，日期 %s），暂停 tick 采集；"
                "其余域不受影响（PRD FR-06 规则 5）",
                limit, written, trade_date,
            )
            break

    elapsed = int((time.time() - start) * 1000)
    coverage = (with_data / len(codes)) if codes else 0.0
    summary.update(
        written_rows=written,
        contracts_with_data=with_data,
        coverage_ratio=round(coverage, 6),
        paused_by_limit=paused,
        failed_contracts=failed,
        duration_ms=elapsed,
        success=(not paused),
    )

    # ── 审计与告警（PRD FR-06 规则 4/5 + 附录 B 埋点） ──
    await _write_event(
        event_type="SYNC_FAILED" if paused else "SYNC_SUCCESS",
        data_source="qmt_tick_collect",
        record_count=written,
        duration_ms=elapsed,
        error=f"写入量超阈值 {limit}，已暂停" if paused else None,
        extra={
            "trade_date": trade_date,
            "contracts_total": len(codes),
            "contracts_with_data": with_data,
            "coverage_ratio": round(coverage, 6),
            "failed_contracts": failed,
        },
    )
    if paused:
        await _write_event(
            event_type="SYNC_FAILED",
            data_source="qmt_tick_limit_pause",
            record_count=written,
            duration_ms=elapsed,
            error=f"written_rows={written} >= threshold={limit}",
            extra={"trade_date": trade_date, "threshold": limit, "resumed": False},
        )
    if coverage < coverage_threshold:
        logger.warning(
            "QMT tick 自检覆盖率 %.2f%% < %.0f%%（%d/%d 只有数据，日期 %s）",
            coverage * 100, coverage_threshold * 100, with_data, len(codes), trade_date,
        )

    logger.info(
        "QMT tick 采集完成: %s 写入 %d 行，有数据 %d/%d（覆盖率 %.2f%%），"
        "失败 %d 只，超限暂停=%s，%dms",
        trade_date, written, with_data, len(codes), coverage * 100,
        failed, paused, elapsed,
    )
    return summary
