"""QmtHealthProbe 单测 — 三层健康检查与 5s 缓存（PRD FR-02）。"""

from datetime import date, timedelta
from pathlib import Path


from app.data.sources.cn.qmt.health import QmtErrorCode, QmtHealthProbe
from tests.data.test_qmt_datadir_reader import (
    _pack_kline,
    _recent_records,
    _three_days_records,
    _write_kline_file,
    _day_sec,
    _yyyymmdd,
)


def _mk_fresh(tmp_path: Path) -> Path:
    recs = _recent_records([2, 1, 0])
    _write_kline_file(tmp_path / 'SH' / '86400' / '000001.DAT', recs)
    _write_kline_file(tmp_path / 'SZ' / '86400' / '000001.DAT', recs)
    return tmp_path


class TestProbeStates:
    def test_not_configured(self):
        state = QmtHealthProbe(datadir="").probe()
        assert state.code == QmtErrorCode.NOT_CONFIGURED
        assert state.ok is False

    def test_path_missing(self, tmp_path):
        state = QmtHealthProbe(datadir=str(tmp_path / 'nope')).probe()
        assert state.code == QmtErrorCode.PATH_MISSING
        assert state.ok is False

    def test_ok_fresh(self, tmp_path):
        state = QmtHealthProbe(datadir=str(_mk_fresh(tmp_path))).probe()
        assert state.ok is True
        assert state.code == QmtErrorCode.OK
        assert state.universe_size == 1
        assert state.latest_trade_date == _yyyymmdd(date.today())

    def test_stale(self, tmp_path):
        """固定历史日期 → 超宽容期判停更（下载任务未运行的典型形态）。"""
        _write_kline_file(
            tmp_path / 'SH' / '86400' / '000001.DAT', _three_days_records()
        )
        _write_kline_file(
            tmp_path / 'SZ' / '86400' / '000001.DAT', _three_days_records()
        )
        state = QmtHealthProbe(datadir=str(tmp_path)).probe()
        assert state.ok is False
        assert state.code == QmtErrorCode.STALE
        assert state.latest_trade_date == '20260909'
        assert '下载任务' in state.message

    def test_self_check_failed(self, tmp_path):
        """文件级 status 漂移 → 拒读样本上报（格式漂移形态）。"""
        recs = _recent_records([2, 1, 0])
        today = date.today()
        bad = _pack_kline(
            _day_sec(today.year, today.month, today.day),
            10.5, 11.0, 10.4, 10.8, 1000, 1, 10.5, status=440,
        )
        _write_kline_file(tmp_path / 'SH' / '86400' / '000001.DAT', recs)
        _write_kline_file(tmp_path / 'SZ' / '86400' / '000001.DAT', recs[:2] + [bad])
        state = QmtHealthProbe(datadir=str(tmp_path)).probe()
        assert state.ok is False
        assert state.code == QmtErrorCode.SELF_CHECK_FAILED
        assert '000001.SZ' in state.rejected_samples

    def test_no_data(self, tmp_path):
        """目录存在但无股票数据文件 → NO_DATA。"""
        state = QmtHealthProbe(datadir=str(tmp_path)).probe()
        assert state.ok is False
        assert state.code == QmtErrorCode.NO_DATA


class TestProbeCache:
    def test_cached_within_ttl(self, tmp_path):
        probe = QmtHealthProbe(datadir=str(_mk_fresh(tmp_path)))
        first = probe.probe()
        second = probe.probe()
        assert first is second  # 5s 缓存内返回同一对象（防轮询风暴）

    def test_refresh_bypasses_cache(self, tmp_path):
        probe = QmtHealthProbe(datadir=str(_mk_fresh(tmp_path)))
        first = probe.probe()
        second = probe.refresh()
        assert first is not second
        assert second.ok is True


class TestRecentTradeDates:
    def test_descending_window(self, tmp_path):
        probe = QmtHealthProbe(datadir=str(_mk_fresh(tmp_path)))
        dates = probe.recent_trade_dates(2)
        assert dates == sorted(dates, reverse=True)
        assert len(dates) == 2
        assert dates[0] == _yyyymmdd(date.today())

    def test_unavailable_empty(self, tmp_path):
        assert QmtHealthProbe(datadir=str(tmp_path / 'nope')).recent_trade_dates(6) == []


class TestReportClosure:
    """健康落库与告警闭环（PRD FR-02 规则 3 / FR-13）。"""

    async def test_report_to_mongo_ok(self, tmp_path, inject_sim_db):
        probe = QmtHealthProbe(datadir=str(_mk_fresh(tmp_path)))
        ok = await probe.report_to_mongo(probe.probe())
        assert ok is True

        docs = await inject_sim_db["source_health"].find({}).to_list(length=5)
        assert len(docs) == 1
        doc = docs[0]
        assert doc["source"] == "qmt"
        assert doc["domain"] == "__datadir__"
        assert doc["circuit_state"] == "closed"
        assert doc["datadir_state"] == "ok"
        assert doc["datadir_freshness"] == _yyyymmdd(date.today())
        assert doc["success_count"] == 1

    async def test_report_to_mongo_stale(self, tmp_path, inject_sim_db):
        _write_kline_file(
            tmp_path / 'SH' / '86400' / '000001.DAT', _three_days_records()
        )
        _write_kline_file(
            tmp_path / 'SZ' / '86400' / '000001.DAT', _three_days_records()
        )
        probe = QmtHealthProbe(datadir=str(tmp_path))
        await probe.report_to_mongo(probe.probe())

        doc = await inject_sim_db["source_health"].find_one({"source": "qmt"})
        assert doc["circuit_state"] == "open"
        assert doc["datadir_state"] == "stale"
        assert doc["failure_count"] == 1
        assert "停更" in doc["last_error"]

    async def test_counters_accumulate_across_probes(self, tmp_path, inject_sim_db):
        """多次探测必须累加计数（PRD 3.2 成功率的前提）。

        原实现用整行 `$set` → 每次探测把计数覆盖成 1/0，成功率永远是 100%/0%。
        """
        fresh = QmtHealthProbe(datadir=str(_mk_fresh(tmp_path)))
        for _ in range(3):
            await fresh.report_to_mongo(fresh.probe())

        doc = await inject_sim_db["source_health"].find_one({"source": "qmt"})
        assert doc["success_count"] == 3
        assert doc["failure_count"] == 0
        assert doc["total_calls"] == 3
        assert doc["success_count"] / doc["total_calls"] == 1.0

        # 再灌两次失败（路径缺失），计数继续累加而非被覆盖
        bad = QmtHealthProbe(datadir=str(tmp_path / "nope"))
        for _ in range(2):
            await bad.report_to_mongo(bad.probe())

        doc = await inject_sim_db["source_health"].find_one({"source": "qmt"})
        assert doc["success_count"] == 3
        assert doc["failure_count"] == 2
        assert doc["total_calls"] == 5
        assert doc["circuit_state"] == "open"

    async def test_report_alert_only_on_failure(self, tmp_path, inject_sim_db):
        # OK 状态：不写告警事件（避免每个交易日产生噪音）
        probe = QmtHealthProbe(datadir=str(_mk_fresh(tmp_path)))
        assert await probe.report_alert(probe.probe()) is False
        events = await inject_sim_db["sync_events"].find({}).to_list(length=5)
        assert events == []

        # 路径缺失：写一条 SYNC_FAILED，带枚举错误码
        bad = QmtHealthProbe(datadir=str(tmp_path / "nope"))
        assert await bad.report_alert(bad.probe()) is True
        events = await inject_sim_db["sync_events"].find({}).to_list(length=5)
        assert len(events) == 1
        assert events[0]["event_type"] == "SYNC_FAILED"
        assert events[0]["error_code"] == "path_missing"
        assert events[0]["domain"] == "__datadir__"


class TestStaleRule:
    """停更判定：优先用平台交易日历的期望最后交易日（PRD FR-02 规则 3）。"""

    def test_lag_one_trading_day_is_stale(self, tmp_path):
        """落后 1 个交易日即判停更 —— 10 日宽容期不会触发，日历口径必须触发。"""
        probe = QmtHealthProbe(datadir=str(_mk_fresh(tmp_path)))
        today = date.today()

        # datadir 最新分区 = 今天 → 不停更
        assert probe.refresh(_yyyymmdd(today)).code == QmtErrorCode.OK

        # 期望是明天（模拟「今天已收盘但 datadir 停在昨天」）→ 落后 1 个交易日即停更
        expected = _yyyymmdd(today + timedelta(days=1))
        state = probe.refresh(expected)
        assert state.code == QmtErrorCode.STALE
        assert state.expected_trade_date == expected
        assert "期望" in state.message

    def test_without_calendar_falls_back_to_tolerance(self, tmp_path):
        """无日历基准 → 退回 10 日宽容期（今天的数据不算停更）。"""
        probe = QmtHealthProbe(datadir=str(_mk_fresh(tmp_path)))
        assert probe.refresh().code == QmtErrorCode.OK

    def test_future_partition_is_not_stale(self):
        """最新分区是未来日（罕见）→ 不判停更，交给自检兜底。"""
        assert QmtHealthProbe._is_stale("20261231", "20261021") is False

    def test_invalid_expected_date_falls_back(self):
        assert QmtHealthProbe._is_stale(_yyyymmdd(date.today()), "bogus") is False

    def test_missing_latest_is_stale(self):
        assert QmtHealthProbe._is_stale(None, "20261021") is True
