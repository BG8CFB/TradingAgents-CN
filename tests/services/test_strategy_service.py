"""策略模板过滤/排序与每日推荐落库测试。"""
import pytest

pytestmark = pytest.mark.requires_db

from app.data.storage.mongo.client import get_motor_db
from app.data.storage.mongo.collections import get_collection_name
from app.data.storage.mongo.repositories.factor_scores_repo import FactorScoresRepo
from app.services.screening.strategy_service import StrategyService

_STRATEGY_IDS = ("volume_breakout", "trend_pullback", "oversold_rebound",
                 "high_roe_low_val", "quality_growth", "steady_inflow")


async def _cleanup():
    db = get_motor_db()
    await db[get_collection_name("factor_scores", "CN")].delete_many(
        {"symbol": {"$regex": "^TESTS"}})
    await db[get_collection_name("screening_recommendations", "CN")].delete_many(
        {"strategy_id": {"$in": list(_STRATEGY_IDS)}})


async def _seed_factors():
    """3 只股 × 同一 trade_date，量纲设计使 volume_breakout 只命中 2 只。"""
    await _cleanup()
    rows = [
        # 命中全部硬条件 + short_term 分最高
        {"symbol": "TESTS001", "trade_date": "2026-09-11", "name": "甲", "industry": "银行",
         "bias_ma20": 3.0, "turnover_amp": 2.0, "macd_golden_days": 3, "main_inflow_5d": 1e8,
         "score_short_term": 95.0, "score_balanced": 80.0, "score_value": 40.0, "ret_5d": 5.0},
        # 命中全部硬条件 + 分数次高
        {"symbol": "TESTS002", "trade_date": "2026-09-11", "name": "乙", "industry": "医药",
         "bias_ma20": 1.0, "turnover_amp": 1.6, "macd_golden_days": 2, "main_inflow_5d": 5e7,
         "score_short_term": 88.0, "score_balanced": 70.0, "score_value": 50.0, "ret_5d": 2.0},
        # 不命中：bias_ma20 < 0
        {"symbol": "TESTS003", "trade_date": "2026-09-11", "name": "丙", "industry": "电子",
         "bias_ma20": -1.0, "turnover_amp": 3.0, "macd_golden_days": 4, "main_inflow_5d": 2e8,
         "score_short_term": 99.0, "score_balanced": 90.0, "score_value": 60.0, "ret_5d": 8.0},
    ]
    await FactorScoresRepo().upsert_many(rows, market="CN")


async def test_list_strategies():  # 只读 YAML，不触 DB，无需 real_mongo_db
    strategies = await StrategyService().list_strategies()
    assert len(strategies) == 6
    default = [s for s in strategies if s["is_default"]]
    assert len(default) == 1 and default[0]["id"] == "volume_breakout"
    s0 = strategies[0]
    assert {"id", "name", "description", "style", "top_n", "is_default",
            "filters"} <= set(s0)


async def test_run_strategy_filters_and_sorts(real_mongo_db):
    await _seed_factors()
    result = await StrategyService().run_strategy("volume_breakout")
    assert result["total"] == 2
    assert [i["symbol"] for i in result["items"]] == ["TESTS001", "TESTS002"]
    item = result["items"][0]
    assert item["score"] == 95.0
    assert item["signals"]  # 命中信号非空
    assert result["as_of"] == "2026-09-11"
    await _cleanup()


async def test_run_strategy_extra_industry_filter(real_mongo_db):
    await _seed_factors()
    result = await StrategyService().run_strategy(
        "volume_breakout", extra_conditions=[{"field": "industry", "op": "==", "value": "银行"}])
    assert result["total"] == 1
    assert result["items"][0]["symbol"] == "TESTS001"
    await _cleanup()


async def test_generate_daily_recommendations_persists(real_mongo_db):
    await _seed_factors()
    summary = await StrategyService().generate_daily_recommendations()
    assert summary["strategies_written"] == 6
    db = get_motor_db()
    coll = db[get_collection_name("screening_recommendations", "CN")]
    doc = await coll.find_one({"strategy_id": "volume_breakout"})
    assert doc and doc["trade_date"] == "2026-09-11"
    assert doc["insight_status"] == "none"
    assert len(doc["items"]) == 2
    # 幂等：重跑不产生重复文档
    await StrategyService().generate_daily_recommendations()
    cnt = await coll.count_documents({"strategy_id": "volume_breakout"})
    assert cnt == 1
    await _cleanup()
