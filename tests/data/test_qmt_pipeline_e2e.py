"""QMT M2 端到端串联验收（技术方案 §8「验收：手工」的自动化替代）。

一条 `run_qmt_sync(force=True)` 打通 M2 已交付的全部域：

    合约列表 → 交易日历 → 日线 → 复权因子（双源保护）
      → 分时（1m/5m 按日分块）→ tick（逐票流式）→ 分红送配

验证四件事：
1. **单次调用全链路成功**（每域各自返回 success，且汇总额正确）；
2. **落库形状**：全部写入既有标准集合，`data_source="qmt"`，无 QMT 方言列；
3. **幂等**：连跑两次，各集合文档数不变（唯一键 upsert 语义）；
4. **开关与隔离**：`QMT_ENABLED=false` 时整体跳过，不产生任何写入。

数据源为合成 datadir（64B K 线 / 144B tick 真实二进制布局，与 reader 自检
兼容）；DB 用项目 SimulatedMongoDB + bulk_write 适配，全程真实代码路径。
"""

from datetime import date, datetime, timedelta, timezone

import pytest

from app.data.storage.mongo.collections import get_collection_name
from tests.data.test_qmt_datadir_reader import (
    _pack_kline,
    _recent_records,
    _write_kline_file,
)
from tests.data.test_qmt_e2e_chain import _install_bulk_write

TZ = timezone(timedelta(hours=8))
_TODAY = date.today()
_D0 = _TODAY.isoformat()
_D0_YMD = _TODAY.strftime("%Y%m%d")
_DAYS_AGO = [2, 1, 0]

# 分时：3 根 5 分钟 bar（09:35 起）
_BARS = [
    (10.0, 10.4, 9.9, 10.2, 120, 122_400),
    (10.2, 10.6, 10.1, 10.5, 80, 84_000),
    (10.5, 10.8, 10.4, 10.6, 60, 63_600),
]
# tick：首条为集合竞价行（open_interest=12），锚定 09:15:00
_TICKS = [
    (0, 10.00, 0, 0, 12, 9.8, 0, (10.0, 10.0, 10.0)),
    (1, 10.10, 101_000, 1000, 0, 9.8, 3, (10.0, 10.2, 9.95)),
    (2, 10.20, 204_000, 2000, 0, 9.8, 7, (10.0, 10.3, 9.95)),
]

_DOMAINS = (
    "basic_info", "trade_calendar", "daily_quotes", "adj_factors",
    "intraday_quotes", "tick_quotes", "corporate_actions",
)


def _minute_records() -> list[bytes]:
    """3 根 5 分钟 K 线记录（与日线同构 64B；文件头由 _write_kline_file 加）。"""
    start = datetime(_TODAY.year, _TODAY.month, _TODAY.day, 9, 35, tzinfo=TZ)
    out = []
    for i, (o, h, low, c, vol, amt) in enumerate(_BARS):
        ts = int((start + timedelta(minutes=5 * i)).timestamp())
        out.append(_pack_kline(ts, o, h, low, c, vol, amt, 9.8))
    return out


def _tick_bytes() -> bytes:
    import struct

    out = []
    for (sec, last, amt, vol, phase, lc, tx, ohlc) in _TICKS:
        o, h, low = ohlc
        out.append(struct.pack(
            "<IIIIQIIIIIIIIII" + "I" * 20,
            sec * 1000, 0, int(last * 1000), 0, int(amt),
            int(vol), int(phase), 0, int(tx), 0,
            int(o * 1000), int(h * 1000), int(low * 1000), 0,
            int(lc * 1000),
            10210, 10220, 0, 0, 0, 10, 20, 0, 0, 0,
            10200, 10190, 0, 0, 0, 30, 40, 0, 0, 0,
        ))
    return b"".join(out)


def _mk_tree(root) -> None:
    """合成就绪 datadir：指数(日历) + 2 只股票 × {日线, 5m, tick}。"""
    daily = _recent_records(_DAYS_AGO)
    _write_kline_file(root / "SH" / "86400" / "000001.DAT", daily)   # 上证指数
    _write_kline_file(root / "SZ" / "86400" / "000001.DAT", daily)
    _write_kline_file(root / "SH" / "86400" / "600000.DAT", daily)

    for market, code in (("SZ", "000001"), ("SH", "600000")):
        # 分时：64B K 线结构 + 8B 头哨兵（同 reader 自检要求）
        _write_kline_file(root / market / "300" / f"{code}.DAT", _minute_records())
        # tick：144B 定长、**无文件头**
        p = root / market / "0" / code / f"{_D0_YMD}.dat"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(_tick_bytes())


def _install_all(db):
    return {
        domain: _install_bulk_write(db, get_collection_name(domain, "CN"))
        for domain in _DOMAINS
    }


async def _run(tmp_path, monkeypatch, db):
    from app.core.config import settings

    _mk_tree(tmp_path)
    for mod in ("provider", "health"):
        monkeypatch.setattr(
            f"app.data.sources.cn.qmt.{mod}.get_qmt_datadir", lambda: str(tmp_path)
        )
    monkeypatch.setattr(settings, "QMT_ENABLED", True)
    monkeypatch.setattr(settings, "QMT_SYNC_LOOKBACK_DAYS", 3)
    monkeypatch.setattr(settings, "QMT_INTRADAY_FREQS", "5min")
    monkeypatch.setattr(settings, "QMT_INTRADAY_LOOKBACK_DAYS", 1)

    collections = _install_all(db)
    from app.worker.qmt.jobs import run_qmt_sync

    summary = await run_qmt_sync(force=True)
    return summary, collections


async def _counts(collections):
    return {
        domain: len(await coll.find({}).to_list(length=10_000))
        for domain, coll in collections.items()
    }


@pytest.mark.asyncio
async def test_full_pipeline_single_call(tmp_path, inject_sim_db, monkeypatch):
    """一次 run_qmt_sync 打通 M2 全部域，并落既有标准集合。"""
    summary, collections = await _run(tmp_path, monkeypatch, inject_sim_db)

    assert summary["success"] is True, summary
    by_domain = {r.get("domain"): r for r in summary["domains"]}
    for domain in ("basic_info", "trade_calendar", "daily_quotes",
                   "adj_factors", "intraday_quotes", "tick_quotes"):
        assert by_domain[domain]["success"] is True, by_domain.get(domain)
    # 分红域无 DividData → 允许失败，但必须被尝试并留痕
    assert by_domain["corporate_actions"]["success"] is False
    assert summary["synced_domains"] >= 6

    counts = await _counts(collections)
    # 2 只股票 × 3 个交易日
    assert counts["daily_quotes"] == 6
    assert counts["adj_factors"] == 6
    # 2 只 × 3 根 5m bar（只回看 1 个交易日）
    assert counts["intraday_quotes"] == 6
    # 2 只 × 3 条 tick
    assert counts["tick_quotes"] == 6
    assert counts["basic_info"] == 2
    assert counts["trade_calendar"] == 3

    # 落库形状：统一 data_source，无方言列
    daily = await collections["daily_quotes"].find({"symbol": "000001"}).to_list(length=10)
    assert len(daily) == 3
    for d in daily:
        assert d["data_source"] == "qmt"
        assert d["market"] == "CN"
        assert d["period"] == "daily"
        for leaked in ("ts_code", "preClose", "time", "adj_f_cum"):
            assert leaked not in d

    intraday = await collections["intraday_quotes"].find({"symbol": "000001"}).to_list(length=10)
    assert {d["freq"] for d in intraday} == {"5min"}
    assert all(x["datetime"].startswith(_D0) for x in intraday)

    tick = await collections["tick_quotes"].find({"symbol": "000001"}).to_list(length=10)
    assert all(x["trade_date"] == _D0 for x in tick)
    assert all(isinstance(x["time_ms"], int) for x in tick)
    assert all(isinstance(x["ask_price"], list) for x in tick)


@pytest.mark.asyncio
async def test_pipeline_is_idempotent(tmp_path, inject_sim_db, monkeypatch):
    """连跑两次：唯一键 upsert，文档数不变。"""
    summary1, collections = await _run(tmp_path, monkeypatch, inject_sim_db)
    counts1 = await _counts(collections)

    from app.worker.qmt.jobs import run_qmt_sync

    summary2 = await run_qmt_sync(force=True)
    counts2 = await _counts(collections)

    assert summary1["success"] is True
    assert summary2["success"] is True
    assert counts1 == counts2, (counts1, counts2)


@pytest.mark.asyncio
async def test_disabled_writes_nothing(tmp_path, inject_sim_db, monkeypatch):
    """开关关闭 → 整体短路，不产生任何数据（PRD FR-10 零回归）。"""
    from app.core.config import settings

    _mk_tree(tmp_path)
    monkeypatch.setattr(
        "app.data.sources.cn.qmt.provider.get_qmt_datadir", lambda: str(tmp_path)
    )
    monkeypatch.setattr(settings, "QMT_ENABLED", False)

    collections = _install_all(inject_sim_db)
    from app.worker.qmt.jobs import run_qmt_sync

    summary = await run_qmt_sync(force=True)
    assert summary["skipped"] is True
    assert summary["reason"] == "QMT_ENABLED=false"
    assert all(c == 0 for c in (await _counts(collections)).values())


@pytest.mark.asyncio
async def test_adj_factors_does_not_overwrite_primary_source(
    tmp_path, inject_sim_db, monkeypatch
):
    """复权因子保主源（FR-07 规则 3）在**真实管道**里生效，而不只在单元层。"""
    from app.core.config import settings

    _mk_tree(tmp_path)
    for mod in ("provider", "health"):
        monkeypatch.setattr(
            f"app.data.sources.cn.qmt.{mod}.get_qmt_datadir", lambda: str(tmp_path)
        )
    monkeypatch.setattr(settings, "QMT_ENABLED", True)
    monkeypatch.setattr(settings, "QMT_SYNC_LOOKBACK_DAYS", 3)
    monkeypatch.setattr(settings, "QMT_INTRADAY_FREQS", "")
    collections = _install_all(inject_sim_db)

    # 预置一条 tushare 记录的因子值（与 qmt 的 107.62 不同）
    adj = collections["adj_factors"]
    await adj.update_one(
        {"symbol": "000001", "trade_date": _D0},
        {"$set": {
            "symbol": "000001", "market": "CN", "data_source": "tushare",
            "trade_date": _D0, "adj_factor": 999.0,
        }},
        upsert=True,
    )

    from app.worker.qmt.jobs import run_qmt_sync

    summary = await run_qmt_sync(force=True)
    adj_result = [r for r in summary["domains"] if r.get("domain") == "adj_factors"][0]
    assert adj_result["cross_check"] is not None
    assert adj_result["cross_check"]["kept_existing"] >= 1

    doc = await adj.find_one({"symbol": "000001", "trade_date": _D0})
    assert doc["adj_factor"] == 999.0          # 保留 tushare 值
    assert doc["data_source"] == "tushare"
