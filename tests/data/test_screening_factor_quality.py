"""选股因子真实计算契约：截止日、披露时点、完整窗口和缺值语义。"""

import math

import numpy as np
import pandas as pd
import pytest

from app.data.factors.engine import FactorScoreEngine
from app.data.schema.domains.factor_scores import FACTOR_FIELDS
from app.data.sources.cn.akshare.adapter import AKShareCNAdapter
from app.data.sources.cn.baostock.adapter import BaoStockCNAdapter
from app.data.sources.cn.tushare.adapter import TushareCNAdapter


AS_OF = "2026-09-30"
ENGINE = FactorScoreEngine()


def _financial(**changes):
    row = dict(symbol="000001", report_period="2026-06-30",
               announce_date="2026-08-28", statement_type="income",
               report_type="H1", data_source="test", net_profit=None,
               roe=None, gross_margin=None, debt_ratio=None)
    row.update(changes)
    return row


def test_financial_merges_nonmissing_same_period_and_excludes_future_rows():
    frame = pd.DataFrame([
        _financial(report_period="2025-06-30", announce_date="2025-08-28", net_profit=100),
        _financial(net_profit=130, roe=18),
        _financial(statement_type="indicator", gross_margin=35),
        _financial(statement_type="balance", debt_ratio=45),
        _financial(report_period="2028-06-30", announce_date="2028-08-28", net_profit=999),
        _financial(announce_date="2026-10-20", net_profit=999, roe=999),
        _financial(statement_type="forecast", roe=999),
    ])
    got = ENGINE._quality_from_frame(frame, AS_OF).loc["000001"]
    assert got["roe"] == 18
    assert got["gross_margin"] == 35
    assert got["debt_ratio"] == 45
    assert got["net_profit_yoy"] == pytest.approx(30)
    assert got["_financial_report_period"] == "2026-06-30"
    assert got["_financial_announce_date"] == "2026-08-28"
    assert got["_net_profit_yoy_method"] == "derived_same_source_statement_period"


@pytest.mark.parametrize("changes", [
    {"announce_date": None}, {"announce_date": "not-a-date"},
    {"announce_date": "2026-10-01"}, {"announce_date": "2026-01-01"},
    {"report_period": "2028-06-30"}, {"statement_type": "forecast"},
])
def test_unproven_or_future_disclosures_do_not_enter_scores(changes):
    got = ENGINE._quality_from_frame(
        pd.DataFrame([_financial(roe=99, **changes)]), AS_OF).iloc[0]
    assert pd.isna(got["roe"])
    assert got["_financial_status"] == "no_disclosed_data"


@pytest.mark.parametrize("changes", [
    {"data_source": "other"}, {"statement_type": "indicator"},
    {"report_type": "Q2"}, {"net_profit": 0}, {"net_profit": -100},
])
def test_yoy_does_not_mix_accounting_rows_or_divide_by_nonpositive_prior(changes):
    previous = _financial(report_period="2025-06-30", announce_date="2025-08-28", net_profit=100)
    previous.update(changes)
    got = ENGINE._quality_from_frame(pd.DataFrame([
        previous, _financial(net_profit=130)]), AS_OF).iloc[0]
    assert pd.isna(got["net_profit_yoy"])
    assert got["_net_profit_yoy_method"] == "unavailable"


def test_zero_current_profit_is_a_real_value_not_missing():
    got = ENGINE._quality_from_frame(pd.DataFrame([
        _financial(report_period="2025-06-30", announce_date="2025-08-28", net_profit=100),
        _financial(net_profit=0)]), AS_OF).iloc[0]
    assert got["net_profit_yoy"] == -100


def test_quality_does_not_fill_new_report_from_old_report():
    got = ENGINE._quality_from_frame(pd.DataFrame([
        _financial(report_period="2025-12-31", announce_date="2026-04-20", debt_ratio=45),
        _financial(roe=18)]), AS_OF).iloc[0]
    assert pd.isna(got["debt_ratio"])
    assert got["roe"] == 18


def _indicators(n=120, end=AS_OF):
    return pd.DataFrame([
        dict(symbol="000001", trade_date=d.strftime("%Y-%m-%d"), pe_ttm=20,
             pb=1.5, dividend_yield=None, volume_ratio=None)
        for d in pd.bdate_range(end=end, periods=n)
    ])


def test_valuation_uses_quote_asof_and_preserves_missing_reported_fields():
    future = _indicators(1, "2026-10-08").assign(pe_ttm=1, volume_ratio=99)
    got = ENGINE._valuation_from_frame(pd.concat([_indicators(), future]), AS_OF).iloc[0]
    assert got["pe_ttm_percentile"] == 100
    assert got["_pe_history_days"] == 120
    assert got["_indicators_trade_date"] == AS_OF
    assert pd.isna(got["volume_ratio"])
    assert pd.isna(got["dividend_yield"])


@pytest.mark.parametrize("count", [1, 5, 119])
def test_short_valuation_history_is_not_a_percentile(count):
    got = ENGINE._valuation_from_frame(_indicators(count), AS_OF).iloc[0]
    assert pd.isna(got["pe_ttm_percentile"])
    assert pd.isna(got["pb_percentile"])
    assert got["_pe_history_days"] == count


def test_duplicate_or_stale_indicators_do_not_make_complete_current_history():
    duplicate = pd.concat([_indicators(1)] * 120)
    assert pd.isna(ENGINE._valuation_from_frame(duplicate, AS_OF).iloc[0]["pe_ttm_percentile"])
    stale = _indicators(120, "2026-09-29").assign(volume_ratio=2, dividend_yield=3)
    got = ENGINE._valuation_from_frame(stale, AS_OF).iloc[0]
    assert pd.isna(got["pe_ttm_percentile"])
    assert pd.isna(got["volume_ratio"])
    assert pd.isna(got["dividend_yield"])


def _flow_inputs():
    dates = [d.strftime("%Y-%m-%d") for d in pd.bdate_range(end=AS_OF, periods=5)]
    flow = pd.DataFrame([dict(symbol="000001", trade_date=d, main_net_inflow=10) for d in dates])
    amounts = pd.DataFrame([dict(symbol="000001", trade_date=d, amount=100) for d in dates])
    return dates, flow, amounts


def test_complete_five_day_flow_and_real_zero():
    dates, flow, amounts = _flow_inputs()
    got = ENGINE._flow_from_frames(flow, amounts, dates).iloc[0]
    assert got["main_inflow_5d"] == 50
    assert got["main_inflow_5d_pct"] == 10
    zero = ENGINE._flow_from_frames(flow.assign(main_net_inflow=0), amounts, dates).iloc[0]
    assert zero["main_inflow_5d"] == 0
    assert zero["main_inflow_5d_pct"] == 0


@pytest.mark.parametrize("case", ["missing_day", "all_missing", "duplicate_day", "conflict"])
def test_incomplete_flow_is_not_zero_or_five_day_total(case):
    dates, flow, amounts = _flow_inputs()
    if case == "missing_day":
        flow = flow.iloc[:-1]
    elif case == "all_missing":
        flow["main_net_inflow"] = np.nan
    elif case == "duplicate_day":
        flow = pd.concat([flow.iloc[:1]] * 5)
    else:
        flow = pd.concat([flow, flow.iloc[:1].assign(main_net_inflow=99)])
    got = ENGINE._flow_from_frames(flow, amounts, dates).iloc[0]
    assert pd.isna(got["main_inflow_5d"])
    assert pd.isna(got["main_inflow_5d_pct"])
    assert got["_money_flow_days"] < 5


def test_amount_requires_matching_complete_five_days():
    dates, flow, amounts = _flow_inputs()
    got = ENGINE._flow_from_frames(flow, amounts.iloc[:-1], dates).iloc[0]
    assert got["main_inflow_5d"] == 50
    assert pd.isna(got["main_inflow_5d_pct"])


def test_quality_metadata_and_null_factors_survive_serialization():
    row = dict.fromkeys(FACTOR_FIELDS, np.nan)
    row.update(symbol="000001", name="测试", industry="银行", trade_date=AS_OF,
               score_short_term=np.nan, score_balanced=np.nan, score_value=np.nan,
               _pe_history_days=5, _money_flow_days=4)
    got = ENGINE._to_records(pd.DataFrame([row]), "CN")[0]
    assert got["main_inflow_5d"] is None
    assert got["pe_ttm_percentile"] is None
    assert got["score_value"] is None  # 重算缺值必须覆盖旧分数，不能保留 stale 分数
    assert got["data_quality"]["as_of"] == AS_OF
    assert got["data_quality"]["valuation_minimum_history_days"] == 120
    assert got["data_quality"]["valuation_window_trade_days"] == 500
    assert got["data_quality"]["pe_history_days"] == 5
    assert got["data_quality"]["financial_status"] == "no_disclosed_data"
    assert "_money_flow_days" not in got


@pytest.mark.parametrize("adapter, raw", [
    (AKShareCNAdapter, dict(symbol="000001", report_period="2026-06-30", ann_date="2026-08-28")),
    (TushareCNAdapter, dict(ts_code="000001.SZ", end_date="20260630", ann_date="20260828")),
    (BaoStockCNAdapter, dict(code="sz.000001", statDate="2026-06-30", pubDate="2026-08-28")),
])
def test_financial_adapters_preserve_real_disclosure_and_zero_profit(adapter, raw):
    got = adapter().adapt_financial_data([dict(raw, net_profit=0)])[0]
    assert got.report_period == "2026-06-30"
    assert got.announce_date == "2026-08-28"
    assert got.net_profit == 0


@pytest.mark.parametrize("adapter, raw", [
    (TushareCNAdapter, dict(ts_code="000001.SZ", ann_date="20260828")),
    (BaoStockCNAdapter, dict(code="sz.000001", pubDate="2026-08-28")),
])
def test_disclosure_date_is_not_substituted_for_report_period(adapter, raw):
    got = adapter().adapt_financial_data([raw])[0]
    assert got.report_period is None
    assert got.announce_date == "2026-08-28"


@pytest.mark.requires_db
async def test_real_mongo_engine_excludes_future_inputs_and_keeps_missing_flow(
        real_mongo_db, seed_factor_inputs):
    from app.data.storage.mongo.collections import get_collection_name

    db = real_mongo_db
    symbol = seed_factor_inputs["symbols"][0]
    dates = seed_factor_inputs["dates"]
    quotes = db[get_collection_name("daily_quotes", "CN")]
    indicators = db[get_collection_name("daily_indicators", "CN")]
    financial = db[get_collection_name("financial_data", "CN")]
    flow = db[get_collection_name("money_flow", "CN")]
    await quotes.insert_one(dict(symbol=symbol, trade_date="2099-01-01", period="daily",
                                 close=999, volume=999, amount=999))
    await indicators.insert_one(dict(symbol=symbol, trade_date="2099-01-01",
                                     pe_ttm=0.1, pb=0.1, volume_ratio=999))
    await financial.insert_one(dict(symbol=symbol, report_period="2098-12-31",
                                    announce_date="2099-01-01", statement_type="indicator",
                                    roe=999, data_source="test"))
    await financial.update_one({"symbol": symbol, "report_period": "2026-06-30"},
                               {"$unset": {"debt_ratio": ""}})
    await financial.insert_one(dict(symbol=symbol, report_period="2026-06-30",
                                    announce_date="2026-08-31", statement_type="balance",
                                    debt_ratio=45, data_source="test"))
    await flow.delete_one({"symbol": symbol, "trade_date": dates[-1]})
    got = (await ENGINE.compute_factors("CN")).set_index("symbol").loc[symbol]
    assert got["trade_date"] == dates[-1]
    assert got["volume_ratio"] == 1.8
    assert got["roe"] == 18
    assert got["debt_ratio"] == 45
    assert math.isclose(got["net_profit_yoy"], 30)
    assert pd.isna(got["main_inflow_5d"])
    assert got["_money_flow_days"] == 4


@pytest.mark.requires_db
async def test_complete_factor_batch_removes_excluded_rows_but_keeps_other_dates(real_mongo_db):
    from app.data.storage.mongo.collections import get_collection_name
    from app.data.storage.mongo.repositories.factor_scores_repo import FactorScoresRepo

    coll = real_mongo_db[get_collection_name("factor_scores", "CN")]
    symbols = ["TESTBATCH_KEEP", "TESTBATCH_REMOVE"]
    date = "1901-01-02"
    try:
        await coll.insert_many([
            dict(symbol=symbols[0], trade_date=date, score_short_term=50),
            dict(symbol=symbols[1], trade_date=date, score_short_term=90),
            dict(symbol=symbols[1], trade_date="1901-01-01", score_short_term=90),
        ])
        result = await FactorScoresRepo().replace_complete_date([
            dict(symbol=symbols[0], trade_date=date, score_short_term=70)
        ], "CN", date)
        assert result == {"written": 1, "removed": 1}
        rows = await coll.find({"trade_date": date}).to_list(length=None)
        assert [row["symbol"] for row in rows] == [symbols[0]]
        assert rows[0]["score_short_term"] == 70
        assert await coll.count_documents({"symbol": symbols[1], "trade_date": "1901-01-01"}) == 1
        # 完整计算后全部剔除是合法空快照，不应继续流通上次推荐因子。
        assert await FactorScoresRepo().replace_complete_date([], "CN", date) == {
            "written": 0, "removed": 1}
    finally:
        await coll.delete_many({"symbol": {"$in": symbols}})


@pytest.mark.requires_db
async def test_partial_factor_write_failure_does_not_delete_previous_excluded_rows(real_mongo_db):
    from bson.errors import InvalidDocument
    from app.data.storage.mongo.collections import get_collection_name
    from app.data.storage.mongo.repositories.factor_scores_repo import FactorScoresRepo

    coll = real_mongo_db[get_collection_name("factor_scores", "CN")]
    date = "1901-01-03"
    symbols = [f"TESTBATCH_FAIL_{index:03}" for index in range(501)]
    excluded = "TESTBATCH_FAIL_OLD"
    try:
        await coll.insert_one(dict(symbol=excluded, trade_date=date, score_value=88))
        records = [dict(symbol=symbol, trade_date=date, score_value=50) for symbol in symbols]
        # 前 500 条真实写入后，第二批在 BSON 编码中失败；不替换数据库或写入方法。
        records[-1]["score_value"] = object()
        with pytest.raises(InvalidDocument):
            await FactorScoresRepo().replace_complete_date(records, "CN", date)
        assert await coll.count_documents({"symbol": {"$in": symbols}}) == 500
        assert (await coll.find_one({"symbol": excluded}))["score_value"] == 88
    finally:
        await coll.delete_many({"symbol": {"$in": symbols + [excluded]}})


@pytest.mark.requires_db
async def test_invalid_complete_batch_fails_before_any_mutation(real_mongo_db):
    from app.data.storage.mongo.collections import get_collection_name
    from app.data.storage.mongo.repositories.factor_scores_repo import FactorScoresRepo

    coll = real_mongo_db[get_collection_name("factor_scores", "CN")]
    symbol = "TESTBATCH_INVALID"
    try:
        await coll.insert_one(dict(symbol=symbol, trade_date="1901-01-04", score_value=88))
        with pytest.raises(ValueError):
            await FactorScoresRepo().replace_complete_date([
                dict(symbol=symbol, trade_date="1901-01-05", score_value=50)
            ], "CN", "1901-01-04")
        assert (await coll.find_one({"symbol": symbol}))["score_value"] == 88
        assert await coll.count_documents({"symbol": symbol}) == 1
    finally:
        await coll.delete_many({"symbol": symbol})


@pytest.mark.requires_db
async def test_engine_store_prunes_old_same_day_filtered_factor(real_mongo_db, seed_factor_inputs):
    from app.data.storage.mongo.collections import get_collection_name

    coll = real_mongo_db[get_collection_name("factor_scores", "CN")]
    symbol = "TESTBATCH_EXCLUDED"
    date = seed_factor_inputs["dates"][-1]
    try:
        await coll.insert_one(dict(symbol=symbol, trade_date=date, score_value=99))
        result = await ENGINE.compute_and_store("CN")
        assert result["status"] == "ok"
        assert result["removed"] == 1
        assert await coll.count_documents({"symbol": symbol}) == 0
        basic = real_mongo_db[get_collection_name("basic_info", "CN")]
        await basic.update_many({"symbol": {"$in": seed_factor_inputs["symbols"]}},
                                {"$set": {"name": "ST测试"}})
        empty = await ENGINE.compute_and_store("CN")
        assert empty["status"] == "ok"
        assert empty["symbols"] == 0
        assert empty["removed"] == len(seed_factor_inputs["symbols"])
        assert await coll.count_documents({"trade_date": date}) == 0
    finally:
        await coll.delete_many({"symbol": symbol})
