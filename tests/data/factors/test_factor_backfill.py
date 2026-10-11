"""因子分「指定日期计算」与「缺口补算」的守卫用例（不连库：替换取数与落库）。

背景：FactorScoreEngine.compute_and_store 原先只算 daily_quotes 的**最新单日**；
若某交易日跑批时当日行情尚未入库（同步慢/失败），那次会回退算上一日，且之后每次跑
都只算「当时最新」→ 该交易日永久缺失。本用例锁定三件事：

  ① as_of 必须过滤掉晚于该日的交易日（否则会拿未来数据算历史）；
  ② 指定 as_of 但该日无行情时**绝不落库**（否则写入错位数据）；
  ③ 缺口检测只补「缺的」、且受 max_dates 上限保护。
"""
import pandas as pd
import pytest

from app.data.factors import engine as engine_mod
from app.data.factors.engine import FactorScoreEngine


class _FakeColl:
    def __init__(self, db, coll):
        self.db, self.coll = db, coll

    async def distinct(self, field, query=None):
        if self.coll.endswith("daily_quotes"):
            return self.db.quote_dates
        if query is not None:  # factor_scores 带 $in 过滤
            want = set((query.get("trade_date") or {}).get("$in") or [])
            return [d for d in self.db.stored_dates if d in want]
        return self.db.stored_dates


class _FakeMotorDB:
    def __init__(self, quote_dates, stored_dates):
        self.quote_dates = quote_dates
        self.stored_dates = stored_dates

    def __getitem__(self, coll):
        return _FakeColl(self, coll)


@pytest.mark.asyncio
async def test_recent_trade_dates_as_of_filters_future(monkeypatch):
    db = _FakeMotorDB(["2026-10-09", "2026-10-08", "2026-09-30"], [])
    monkeypatch.setattr(engine_mod, "get_motor_db", lambda: db)
    eng = FactorScoreEngine()
    dates = await eng._recent_trade_dates("CN", "stock_daily_quotes", 10, as_of="2026-10-08")
    assert dates == ["2026-10-08", "2026-09-30"], "as_of 必须过滤掉晚于该日的交易日"


@pytest.mark.asyncio
async def test_compute_and_store_skips_when_as_of_unavailable(monkeypatch):
    eng = FactorScoreEngine()
    calls = {"upsert": 0}

    async def fake_compute(market="CN", as_of=None):
        # 库里该日无行情 → 引擎回退算出的是上一日
        return pd.DataFrame([{"symbol": "000001", "trade_date": "2026-10-08"}])

    class _Repo:
        async def upsert_many(self, records, market):
            calls["upsert"] += 1
            return len(records)

    monkeypatch.setattr(eng, "compute_factors", fake_compute)
    monkeypatch.setattr(engine_mod, "FactorScoresRepo", lambda: _Repo())

    res = await eng.compute_and_store("CN", as_of="2026-10-09")
    assert res["status"] == "skipped" and res["reason"] == "as_of_not_available", res
    assert calls["upsert"] == 0, "日期对不上时绝不能落库（否则写入错位数据）"


@pytest.mark.asyncio
async def test_backfill_missing_only_fills_gaps_and_respects_max(monkeypatch):
    eng = FactorScoreEngine()
    db = _FakeMotorDB(
        ["2026-10-09", "2026-10-08", "2026-09-30", "2026-09-29", "2026-09-28"],
        ["2026-10-08", "2026-09-30"],  # 库里已有这两天
    )
    monkeypatch.setattr(engine_mod, "get_motor_db", lambda: db)
    calls = []

    async def fake_store(market="CN", as_of=None):
        calls.append(as_of)
        return {"status": "ok", "trade_date": as_of, "symbols": 1, "written": 1}

    monkeypatch.setattr(eng, "compute_and_store", fake_store)

    res = await eng.backfill_missing("CN", lookback=5, max_dates=2)
    assert res["missing"] == ["2026-10-09", "2026-09-29", "2026-09-28"], res
    assert res["filled"] == ["2026-10-09", "2026-09-29"], "补算必须受 max_dates 上限保护"
    assert calls == ["2026-10-09", "2026-09-29"], "已存在的交易日不应被重复补算"
