"""QMT 健康探针 — datadir 三层检查（PRD FR-02 / 技术方案 5.5）。

三层：路径可读 → 抽样四级自检（reader.self_check）→ 数据新鲜度。
结果供三方复用：QmtProvider.connect()/is_available()、Web UI 数据源管理页
「连通性测试」（_test_qmt）、worker 采集入口的就绪轮询（DD-07）。

探测为纯文件 IO，5s 进程内缓存防健康页轮询风暴（PRD FR-02 规则 1）。
"""

import logging
import time
from dataclasses import dataclass, field
from datetime import date, datetime
from enum import Enum
from typing import List, Optional, Tuple

from .config import get_qmt_datadir
from .datadir_reader import QmtDatadirReader

logger = logging.getLogger("sources.CN.qmt.health")

# 停更判定宽容期（自然日）：datadir 日历派生自本机数据，无法区分节假日与
# 停更，取 10 日宽容覆盖最长假期（国庆+中秋）；更精确的新鲜度规则由平台
# freshness_rules.yaml 与 sync_events 告警承接（M2 对齐）。
_STALE_TOLERANCE_DAYS = 10


class QmtErrorCode(str, Enum):
    """QMT 源故障错误码（PRD 八「可观测」：杜绝无分类失败）。"""

    OK = "ok"
    NOT_CONFIGURED = "not_configured"      # 未配置 datadir 路径
    PATH_MISSING = "path_missing"          # datadir 路径不存在/不可读
    SELF_CHECK_FAILED = "self_check_failed"  # 抽样四级自检拒读（格式漂移/文件损坏）
    NO_DATA = "no_data"                    # 目录存在但无日线数据文件
    STALE = "stale"                        # 数据停更（下载任务未运行）


@dataclass
class QmtHealthState:
    """单次探测结果（Web UI 三态文案的数据来源，PRD 7.4）。"""

    code: QmtErrorCode
    ok: bool
    message: str = ""
    universe_size: int = 0
    checked_files: int = 0
    rejected_samples: List[str] = field(default_factory=list)
    latest_trade_date: Optional[str] = None  # YYYYMMDD
    expected_trade_date: Optional[str] = None  # 平台日历期望的最后交易日（YYYYMMDD）
    checked_at: Optional[str] = None         # ISO 时刻（诊断用）


class QmtHealthProbe:
    """datadir 健康探针（进程内可复用；探测成本随 5s 缓存摊销）。"""

    _CACHE_TTL_SECONDS = 5.0

    def __init__(self, datadir: Optional[str] = None):
        self._datadir = datadir if datadir is not None else get_qmt_datadir()
        # 空路径构造合法（available=False → PATH_MISSING 分支）
        self._reader = QmtDatadirReader(self._datadir or "")
        self._cache: Optional[Tuple[QmtHealthState, float]] = None

    @property
    def datadir(self) -> str:
        return self._datadir

    def probe(
        self, expected_last_trade_date: Optional[str] = None,
    ) -> QmtHealthState:
        """三层探测（带 5s 缓存）。

        Args:
            expected_last_trade_date: 平台交易日历给出的「期望最后交易日」
                （'YYYYMMDD'）。传入时 stale 判定 = ``最新分区 < 期望最后交易日``
                （PRD FR-02 规则 3：落后任一交易日即停更）；不传则退化为
                10 个自然日宽容期（无日历基准时的降级路径）。
        """
        now = time.monotonic()
        if self._cache is not None:
            state, ts = self._cache
            if now - ts < self._CACHE_TTL_SECONDS:
                return state
        state = self._probe_once(expected_last_trade_date)
        self._cache = (state, now)
        return state

    def refresh(
        self, expected_last_trade_date: Optional[str] = None,
    ) -> QmtHealthState:
        """强制重探（绕过缓存；Web UI「立即自检」用）。"""
        self._cache = None
        return self.probe(expected_last_trade_date)

    def recent_trade_dates(self, n: int = 6) -> List[str]:
        """最近 n 个交易日（YYYYMMDD 降序；worker 采集日期窗口用）。

        直接读日历文件（单文件 ~5700 条，毫秒级），不走 5s 缓存。
        datadir 不可用返回空列表。
        """
        dates = self._reader.trading_dates()
        return sorted(dates, reverse=True)[:n] if dates else []

    # ---------- 内部 ----------

    def _probe_once(self, expected_last_trade_date: Optional[str] = None) -> QmtHealthState:
        if not self._datadir:
            return QmtHealthState(
                code=QmtErrorCode.NOT_CONFIGURED,
                ok=False,
                message="未配置 datadir 路径（Web UI 数据源管理页或 QMT_DATADIR 环境变量）",
                checked_at=datetime.now().isoformat(timespec="seconds"),
            )
        report = self._reader.self_check()
        base = {
            "universe_size": report.universe_size,
            "checked_files": report.checked_files,
            "rejected_samples": list(report.rejected_samples),
            "latest_trade_date": report.latest_trade_date,
            "expected_trade_date": expected_last_trade_date,
            "checked_at": datetime.now().isoformat(timespec="seconds"),
        }
        if report.path_missing:
            return QmtHealthState(
                code=QmtErrorCode.PATH_MISSING,
                ok=False,
                message=f"datadir 路径不存在：{self._datadir}（请检查国金 QMT 客户端安装路径配置）",
                **base,
            )
        if report.universe_size == 0:
            return QmtHealthState(
                code=QmtErrorCode.NO_DATA,
                ok=False,
                message="datadir 中未发现日线数据文件（请确认客户端「盘后自续下载任务」已配置并运行过）",
                **base,
            )
        if report.rejected_samples:
            return QmtHealthState(
                code=QmtErrorCode.SELF_CHECK_FAILED,
                ok=False,
                message=f"本地数据校验失败（自检拒读样本：{', '.join(report.rejected_samples)}），疑似客户端升级导致格式漂移",
                **base,
            )
        stale = self._is_stale(report.latest_trade_date, expected_last_trade_date)
        if stale:
            expected_hint = (
                f"，期望 {expected_last_trade_date}（平台交易日历）"
                if expected_last_trade_date else ""
            )
            return QmtHealthState(
                code=QmtErrorCode.STALE,
                ok=False,
                message=(
                    f"数据停更：最新分区 {report.latest_trade_date}{expected_hint}"
                    f"（请检查国金 QMT 客户端是否运行、下载任务是否正常）"
                ),
                **base,
            )
        return QmtHealthState(
            code=QmtErrorCode.OK,
            ok=True,
            message=f"datadir 就绪（宇宙 {report.universe_size} 只，最新分区 {report.latest_trade_date}）",
            **base,
        )

    @staticmethod
    def _is_stale(
        latest_yyyymmdd: Optional[str],
        expected_yyyymmdd: Optional[str] = None,
    ) -> bool:
        """最新分区是否停更。

        首选口径（PRD FR-02 规则 3）：**落后平台交易日历的最后一个已收盘交易日
        即停更**（``expected_yyyymmdd`` 由调用方注入，探针本身保持纯文件 IO）。

        无日历基准时退化为 10 个自然日宽容期 —— 这是**降级路径**而非等价实现：
        datadir 的日历派生自本机数据，停更时它自己也停更，无法自证「今天是
        交易日」，所以必须由平台日历提供期望值。
        """
        if not latest_yyyymmdd:
            return True
        try:
            latest = datetime.strptime(latest_yyyymmdd, "%Y%m%d").date()
        except ValueError:
            return True
        if expected_yyyymmdd:
            try:
                expected = datetime.strptime(expected_yyyymmdd, "%Y%m%d").date()
            except ValueError:
                expected = None
            if expected is not None:
                # 未来日异常罕见，不判停更（交给自检兜底）
                return latest < expected
        today = date.today()
        return (today - latest).days > _STALE_TOLERANCE_DAYS

    # ---------- 健康落库与告警闭环（PRD FR-02 规则 3 / FR-13） ----------

    async def report_to_mongo(self, state: Optional[QmtHealthState] = None) -> bool:
        """把探测结果写入 ``source_health``（domain="__datadir__" 汇总行）。

        设计取舍：datadir 状态是**源级**而非域级，用 domain="__datadir__"
        单独占一行，避免把同一状态重复写进 daily_quotes/basic_info 等域而
        污染各域的成功率统计（那些仍由 router 的 record_call 负责）。
        写入失败只记日志，不影响采集主流程。

        计数语义：探针每次只知道「这一次」成败，故 success/failure/total
        走 ``$inc`` 累加（``accumulate_health``）—— 用整行 ``$set`` 会把计数
        永远覆盖成 1/0，使 PRD 3.2 的「QMT 采集成功率」指标失去意义。
        ``consecutive_failures`` 仍是单次观测值（成功归零 / 失败记 1），
        精确的连续失败次数由 router 侧的 SourceHealthMonitor 维护。
        """
        st = state or self.probe()
        domain = "__datadir__"
        try:
            from app.data.storage.mongo.repositories.metadata_repo import MetadataRepo

            data = {
                "source": "qmt",
                "domain": domain,
                "market": "CN",
                "circuit_state": "closed" if st.ok else "open",
                "success_count": 1 if st.ok else 0,
                "failure_count": 0 if st.ok else 1,
                "consecutive_failures": 0 if st.ok else 1,
                "total_calls": 1,
                "last_error": None if st.ok else st.message,
                # qmt 特有可观测字段（供健康页展示）
                "datadir": self._datadir,
                "datadir_state": st.code.value,
                "datadir_freshness": st.latest_trade_date,
                "datadir_expected": st.expected_trade_date,
                "datadir_universe_size": st.universe_size,
                "datadir_checked_files": st.checked_files,
            }
            await MetadataRepo().accumulate_health(
                "CN", "qmt", domain, data,
                inc_fields=["success_count", "failure_count", "total_calls"],
            )
            return True
        except Exception as e:  # noqa: BLE001 — 健康上报不得影响采集
            logger.debug("QMT 健康落库失败（忽略）: %s", e)
            return False

    async def report_alert(self, state: Optional[QmtHealthState] = None) -> bool:
        """异常态写一条 ``sync_events`` 告警记录（可审计，PRD FR-13）。

        仅在非 OK 状态写入，避免每个交易日产生噪音事件；事件类型沿用
        平台枚举 ``SYNC_FAILED``，domain 用 "__datadir__" 与健康行对应。
        """
        st = state or self.probe()
        if st.ok:
            return False
        try:
            from app.data.storage.mongo.client import get_motor_db
            from app.data.storage.mongo.collections import get_collection_name
            from app.utils.timezone import now_utc

            db = get_motor_db()
            await db[get_collection_name("sync_events", "CN")].insert_one({
                "event_type": "SYNC_FAILED",
                "domain": "__datadir__",
                "source": "qmt",
                "market": "CN",
                "symbol": None,
                "record_count": 0,
                "duration_ms": 0,
                "error_message": st.message,
                "error_code": st.code.value,
                "data_source": "qmt_health_probe",
                "updated_at": now_utc().isoformat(),
            })
            return True
        except Exception as e:  # noqa: BLE001
            logger.debug("QMT 告警事件写入失败（忽略）: %s", e)
            return False
