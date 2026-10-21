"""QMT 盘后采集任务（PRD FR-11 / 技术方案 5.4 / DD-07）。"""

import asyncio
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

from app.core.config import settings
from app.worker.base_market_sync import BaseMarketDomainSync

logger = logging.getLogger("worker.qmt")


class _QmtPinnedSync(BaseMarketDomainSync):
    """固定 qmt 单源的域同步基类。

    覆写 ``get_sources()`` 钉死 ``["qmt"]``：QMT 采集任务的语义是「本地
    直读零成本优先采」，不能走全量优先级链（否则 tushare 先行，qmt 永远
    轮不到）；失败也不在本任务内降级到既有源——那由 freshness patrol /
    按需刷新的回退链接管（D-2 兜底源定位）。
    """

    market = "CN"

    async def get_sources(self) -> List[str]:
        return ["qmt"]


class QmtBasicInfoSync(_QmtPinnedSync):
    domain = "basic_info"
    description = "QMT 合约列表同步（datadir 宇宙枚举）"


class QmtTradeCalendarSync(_QmtPinnedSync):
    domain = "trade_calendar"
    description = "QMT 交易日历同步（上证指数日线派生）"


class QmtDailyQuotesSync(_QmtPinnedSync):
    domain = "daily_quotes"
    description = "QMT 日线同步（全市场按交易日批量）"


class QmtIntradayQuotesSync(_QmtPinnedSync):
    domain = "intraday_quotes"
    description = "QMT 分时同步（全市场按交易日批量，1m/5m）"


class QmtAdjFactorsSync(_QmtPinnedSync):
    """复权因子同步 —— 覆写 `_persist` 走保主源写入（PRD FR-07 规则 3）。

    与 qmt 其余域的关键差异：**不与既有源抢写**。既有 tushare 记录存在且
    数值不一致时保留 tushare 值并计入不一致率，超阈值告警（见 guarded_write）。
    """

    domain = "adj_factors"
    description = "QMT 复权因子同步（双源校验，保留既有源值）"

    async def _persist(self, records, source_name: str) -> int:
        from app.worker.qmt.guarded_write import write_preserving_primary

        self.last_guard = await write_preserving_primary(
            self.domain, records, self.market,
            compare_fields=("adj_factor",),
            source="qmt",
        )
        return int(self.last_guard.get("written") or 0)


class QmtCorporateActionsSync(_QmtPinnedSync):
    """分红送配同步（CN 域内 qmt 为唯一源，故走默认单版本覆盖写入）。"""

    domain = "corporate_actions"
    description = "QMT 分红送配同步（DividData LevelDB）"


def _parse_intraday_freqs(raw: str) -> List[str]:
    """解析 ``QMT_INTRADAY_FREQS``（逗号分隔），未知频率跳过并告警。

    配置错误不应让整轮采集失败（其余域仍有价值），故只跳过不抛异常。
    """
    from app.data.sources.cn.qmt.field_maps import FREQ_TO_READER_PERIOD

    out: List[str] = []
    for item in str(raw or "").split(","):
        key = item.strip().lower()
        if not key:
            continue
        if key not in FREQ_TO_READER_PERIOD:
            logger.warning(
                "忽略不支持的 QMT 分时频率 %r（支持 %s）",
                key, sorted(FREQ_TO_READER_PERIOD),
            )
            continue
        if key not in out:
            out.append(key)
    return out


def _tz() -> ZoneInfo:
    try:
        return ZoneInfo(settings.TIMEZONE)
    except Exception:
        return ZoneInfo("Asia/Shanghai")


def _parse_deadline(hhmm: str) -> datetime:
    """截止时刻（settings.TIMEZONE 时区，避免依赖部署机本地时区）。"""
    now = datetime.now(_tz())
    parts = (hhmm or "22:00").split(":")
    return now.replace(
        hour=int(parts[0]), minute=int(parts[1] if len(parts) > 1 else 0),
        second=0, microsecond=0,
    )


def _yyyymmdd_to_iso(d: str) -> str:
    return f"{d[:4]}-{d[4:6]}-{d[6:8]}"


async def _expected_trade_date() -> Optional[str]:
    """平台交易日历给出的「期望最后交易日」（'YYYYMMDD'）；不可用返回 None。

    停更判定需要它：datadir 的日历派生自本机数据，停更时自己也不更新，无法
    自证「今天是交易日」（PRD FR-02 规则 3）。取不到就退回探针的 10 日宽容期。
    """
    try:
        from app.data.core.market import get_latest_trade_day

        day = await get_latest_trade_day("CN")
        return day.strftime("%Y%m%d") if day else None
    except Exception as e:  # noqa: BLE001 — 日历不可读不应阻断采集
        logger.debug("读取平台交易日历失败（回退宽容期判定）: %s", e)
        return None


async def _wait_datadir_ready(probe, expected_trade_date: Optional[str] = None) -> bool:
    """就绪轮询（DD-07）：固定间隔探测至截止时刻，不注册独立探测定时器。"""
    from app.data.sources.cn.qmt.health import QmtErrorCode

    deadline = _parse_deadline(settings.QMT_READINESS_DEADLINE)
    poll = max(60, int(settings.QMT_READINESS_POLL_SECONDS))
    while True:
        state = probe.probe(expected_trade_date)
        if state.ok:
            return True
        # 未配置 / 路径缺失不会随时间自愈，立即放弃（避免整晚空转）
        if state.code in (QmtErrorCode.NOT_CONFIGURED, QmtErrorCode.PATH_MISSING):
            logger.error("QMT 采集放弃: %s", state.message)
            return False
        now = datetime.now(_tz())
        if now >= deadline:
            logger.error(
                "QMT 采集超时: datadir 未就绪（%s）；当日缺口由补采/既有源承接",
                state.message,
            )
            return False
        logger.info(
            "datadir 未就绪（%s），%ds 后重试（截止 %s）",
            state.message, poll, deadline.strftime("%H:%M"),
        )
        await asyncio.sleep(poll)


async def run_qmt_sync(force: bool = False) -> Dict[str, Any]:
    """QMT 盘后采集入口（调度注册与手动触发共用）。

    顺序（PRD FR-11）：合约列表 → 交易日历 → 日线（最近
    ``QMT_SYNC_LOOKBACK_DAYS`` 个交易日**单次区间批量**读取，每只股票文件
    只解析一次，避免按日重复读全宇宙）。单域失败不阻断后续域；
    ``force=True`` 跳过就绪等待（手动触发场景）。

    Returns:
        汇总结果：``{"success", "synced_domains", "total", "domains": [...]}``
    """
    if not settings.QMT_ENABLED:
        return {"success": False, "skipped": True, "reason": "QMT_ENABLED=false"}
    if not force and not settings.QMT_SYNC_ENABLED:
        return {"success": False, "skipped": True, "reason": "QMT_SYNC_ENABLED=false"}

    from app.data.sources.cn.qmt.health import QmtHealthProbe

    probe = QmtHealthProbe()
    expected = await _expected_trade_date()
    if force:
        state = probe.refresh(expected)
        if not state.ok:
            logger.error("QMT 手动采集放弃: %s", state.message)
            # 健康落库 + 告警事件（PRD FR-02/FR-13 可审计闭环）
            await probe.report_to_mongo(state)
            await probe.report_alert(state)
            return {"success": False, "reason": state.message}
        await probe.report_to_mongo(state)
    else:
        if not await _wait_datadir_ready(probe, expected):
            # 就绪失败/超时也要留痕，否则健康页看不到「等待超时」
            state = probe.probe(expected)
            await probe.report_to_mongo(state)
            await probe.report_alert(state)
            return {"success": False, "reason": "datadir_not_ready"}
        await probe.report_to_mongo(probe.probe(expected))

    results: List[Dict[str, Any]] = []
    results.append(await QmtBasicInfoSync().sync("get_stock_list"))
    results.append(
        await QmtTradeCalendarSync().sync(
            "get_trade_calendar", lambda: {"exchange": "SSE"}
        )
    )

    dates = probe.recent_trade_dates(int(settings.QMT_SYNC_LOOKBACK_DAYS))
    if dates:
        start, end = _yyyymmdd_to_iso(min(dates)), _yyyymmdd_to_iso(max(dates))
        results.append(
            await QmtDailyQuotesSync().sync(
                "get_daily_quotes_batch_range",
                lambda: {"start_date": start, "end_date": end},
            )
        )
        # 复权因子（FR-07，FR-11 顺序：日线之后）：走保主源写入，与 tushare
        # 交叉校验，不一致时保留 tushare 值并计入不一致率告警
        adj_sync = QmtAdjFactorsSync()
        adj_result = await adj_sync.sync(
            "get_adj_factors_batch_range",
            lambda: {"start_date": start, "end_date": end},
        )
        adj_result["cross_check"] = getattr(adj_sync, "last_guard", None)
        results.append(adj_result)
    else:
        logger.warning("QMT 采集: datadir 交易日历为空，跳过日线域")
        results.append({"domain": "daily_quotes", "success": False,
                        "error": "calendar_empty"})

    # 分时（FR-04，PRD FR-11 顺序：日线之后）：按交易日**逐日分块**采集。
    # 全市场单日 5m ≈ 26 万条、1m ≈ 130 万条，整窗口一次拉取会把内存打满，
    # 故每天一次 sync（同时让 sync_events 的 record_count 按日可审计）。
    freqs = _parse_intraday_freqs(settings.QMT_INTRADAY_FREQS)
    lookback = max(1, int(settings.QMT_INTRADAY_LOOKBACK_DAYS))
    intraday_dates = sorted(dates, reverse=True)[:lookback] if dates else []
    if not freqs:
        logger.warning("QMT 采集: QMT_INTRADAY_FREQS 无可识别频率，跳过分时域")
    elif not intraday_dates:
        logger.warning("QMT 采集: datadir 交易日历为空，跳过分时域")
    else:
        for freq in freqs:
            for d in intraday_dates:
                iso = _yyyymmdd_to_iso(d)
                results.append(
                    await QmtIntradayQuotesSync().sync(
                        "get_intraday_quotes_batch_range",
                        lambda iso=iso, freq=freq: {
                            "start_date": iso, "end_date": iso, "freq": freq,
                        },
                    )
                )

    # tick（FR-06，FR-11 顺序：分时之后）：只采**最近一个交易日**。
    # 走流式采集（逐票读→标准化→校验→入库），不用 BaseMarketDomainSync：
    # 单日全市场千万级记录无法一次性 materialize（见 tick_collect 模块注释）。
    if not dates:
        logger.warning("QMT 采集: datadir 交易日历为空，跳过 tick 域")
        results.append({"domain": "tick_quotes", "success": False,
                        "error": "calendar_empty"})
    else:
        from app.worker.qmt.tick_collect import collect_tick

        tick_result = await collect_tick(_yyyymmdd_to_iso(max(dates)))
        tick_result["domain"] = "tick_quotes"
        results.append(tick_result)

    # 分红送配（FR-07，FR-11 顺序：末位「指数/财务」位）。CN 域内 qmt 是唯一源，
    # 走默认单版本覆盖写入。窗口取 [-30d, +60d]：既要捞到近期已除权的，也要
    # 覆盖「已公告但尚未除权（ex_date 在未来）」的事件，否则永远采不到新公告。
    from datetime import date, timedelta

    today = date.today()
    ca_start = (today - timedelta(days=30)).isoformat()
    ca_end = (today + timedelta(days=60)).isoformat()
    results.append(
        await QmtCorporateActionsSync().sync(
            "get_corporate_actions_batch_range",
            lambda: {"start_date": ca_start, "end_date": ca_end},
        )
    )

    ok = [r for r in results if r.get("success")]
    summary = {
        "success": bool(ok),
        "synced_domains": len(ok),
        "total": len(results),
        "domains": results,
    }
    logger.info("QMT 采集完成: %d/%d 域成功", len(ok), len(results))
    return summary
