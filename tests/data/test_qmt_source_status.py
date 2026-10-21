"""QMT 数据源状态查询（P1-4 / PRD FR-13、7.4）测试。

覆盖 `DataSourceService.get_qmt_source_status()` —— 健康页状态卡片的后端：
- 三层探测结论（路径/自检/新鲜度）与最新分区、期望交易日一并返回；
- 累计健康来自 `source_health` 的 `__datadir__` 行（探针计数走 `$inc`）；
- stale 判定用平台交易日历的期望最后交易日（优于 10 日宽容期）。

不触碰 HTTP 层（该环境无 fastapi 依赖）：直接验证服务方法，路由只是薄封装。
"""

from datetime import date, timedelta

import pytest

from tests.data.test_qmt_datadir_reader import _recent_records, _write_kline_file

TODAY = date.today()
_YMD = lambda d: d.strftime("%Y%m%d")       # noqa: E731 — 探针/分区的口径
_ISO = lambda d: d.isoformat()              # noqa: E731 — 交易日历 cal_date 的口径


def _mk_tree(root, days_ago=(2, 1, 0)):
    recs = _recent_records(list(days_ago))
    _write_kline_file(root / "SH" / "86400" / "000001.DAT", recs)
    _write_kline_file(root / "SZ" / "86400" / "000001.DAT", recs)
    return root


async def _put_calendar(db, days):
    from app.data.storage.mongo.client import get_motor_db
    from app.data.storage.mongo.collections import get_collection_name

    coll = get_motor_db()[get_collection_name("trade_calendar", "CN")]
    for d in days:
        await coll.insert_one({
            "exchange": "SSE", "cal_date": d, "is_open": True,
            "symbol": "__calendar__", "market": "CN", "data_source": "tushare",
        })


def _patch_datadir(monkeypatch, path):
    monkeypatch.setattr(
        "app.data.sources.cn.qmt.health.get_qmt_datadir", lambda: str(path)
    )


@pytest.mark.asyncio
async def test_status_ok_without_health_row(tmp_path, inject_sim_db, monkeypatch):
    from app.services.config.data_source_service import DataSourceService

    _mk_tree(tmp_path)
    _patch_datadir(monkeypatch, tmp_path)

    status = await DataSourceService().get_qmt_source_status()

    assert status["source"] == "qmt"
    assert status["state"] == "ok"
    assert status["ok"] is True
    assert status["universe_size"] == 1
    assert status["checked_files"] >= 1
    assert status["latest_trade_date"] == _YMD(TODAY)
    assert status["rejected_samples"] == []
    # 还没有健康行 → 成功率为 None（而不是伪造 100%）
    assert status["health"]["total_calls"] == 0
    assert status["health"]["success_rate"] is None


@pytest.mark.asyncio
async def test_status_exposes_cumulative_health(tmp_path, inject_sim_db, monkeypatch):
    from app.data.sources.cn.qmt.health import QmtHealthProbe
    from app.services.config.data_source_service import DataSourceService

    _mk_tree(tmp_path)
    _patch_datadir(monkeypatch, tmp_path)

    probe = QmtHealthProbe()
    for _ in range(2):
        await probe.report_to_mongo(probe.probe())

    status = await DataSourceService().get_qmt_source_status()
    assert status["health"]["success_count"] == 2
    assert status["health"]["total_calls"] == 2
    assert status["health"]["success_rate"] == 1.0
    assert status["health"]["circuit_state"] == "closed"


@pytest.mark.asyncio
async def test_stale_uses_platform_calendar(tmp_path, inject_sim_db, monkeypatch):
    """datadir 落后 2 天但日历期望是今天 → 停更（宽容期不会触发）。"""
    from app.services.config.data_source_service import DataSourceService

    # datadir 只到前天（缺昨天与今天）
    _mk_tree(tmp_path, days_ago=(2,))
    _patch_datadir(monkeypatch, tmp_path)
    await _put_calendar(inject_sim_db, [_ISO(TODAY)])

    from app.data.core.market import get_latest_trade_day

    assert await get_latest_trade_day("CN") == TODAY   # 日历基准确实可读

    status = await DataSourceService().get_qmt_source_status()

    assert status["expected_trade_date"] == _YMD(TODAY), status
    assert status["latest_trade_date"] == _YMD(TODAY - timedelta(days=2))
    assert status["state"] == "stale"
    assert status["ok"] is False
    assert "期望" in status["message"]


@pytest.mark.asyncio
async def test_not_configured_state(inject_sim_db, monkeypatch):
    from app.services.config.data_source_service import DataSourceService

    _patch_datadir(monkeypatch, "")
    status = await DataSourceService().get_qmt_source_status()
    assert status["state"] == "not_configured"
    assert status["ok"] is False
    assert status["datadir"] == ""
