"""选股新三域仓储真实读写测试（连 tradingagents_test 隔离库）。"""

import pytest

pytestmark = pytest.mark.requires_db

from datetime import datetime

from app.data.storage.mongo.client import get_motor_db
from app.data.storage.mongo.collections import get_collection_name
from app.data.storage.mongo.repositories.factor_scores_repo import FactorScoresRepo
from app.data.storage.mongo.repositories.screening_recommendations_repo import (
    ScreeningRecommendationsRepo,
)
from app.data.storage.mongo.repositories.screening_insights_repo import (
    ScreeningInsightsRepo,
)


async def _cleanup():
    db = get_motor_db()
    for domain in ("factor_scores", "screening_recommendations"):
        await db[get_collection_name(domain, "CN")].delete_many(
            {"symbol": {"$regex": "^TEST"}}
        )
    await db[get_collection_name("screening_recommendations", "CN")].delete_many(
        {"strategy_id": "test_strategy"}
    )
    await db[get_collection_name("screening_insights", "CN")].delete_many(
        {"user_id": "test_user_screening"}
    )


async def test_factor_scores_upsert_and_query(real_mongo_db):
    await _cleanup()
    repo = FactorScoresRepo()
    rows = [
        {"symbol": "TEST001", "trade_date": "2026-09-11", "industry": "银行",
         "ret_5d": 1.0, "score_short_term": 80.0, "data_source": "computed"},
        {"symbol": "TEST001", "trade_date": "2026-09-12", "industry": "银行",
         "ret_5d": 2.0, "score_short_term": 90.0, "data_source": "computed"},
    ]
    n = await repo.upsert_many(rows, market="CN")
    assert n == 2
    # 幂等：同主键 upsert 覆盖不新增
    await repo.upsert_many([rows[1]], market="CN")
    by_date = await repo.get_all_by_date("CN", "2026-09-12")
    assert {r["symbol"] for r in by_date} == {"TEST001"}
    assert by_date[0]["score_short_term"] == 90.0
    latest = await repo.get_latest_trade_date("CN")
    assert latest == "2026-09-12"
    rng = await repo.get_by_symbol_and_range("TEST001", "CN", "2026-09-11", "2026-09-12")
    assert len(rng) == 2
    await _cleanup()


async def test_recommendations_upsert_latest(real_mongo_db):
    await _cleanup()
    repo = ScreeningRecommendationsRepo()
    doc = {"strategy_id": "test_strategy", "trade_date": "2026-09-12",
           "strategy_name": "测试", "style": "short_term", "total": 1,
           "items": [{"symbol": "TEST001", "score": 88.0}],
           "insight_status": "none"}
    await repo.upsert_daily(doc, market="CN")
    got = await repo.get_latest_by_strategy("CN", "test_strategy")
    assert got["trade_date"] == "2026-09-12"
    assert got["items"][0]["symbol"] == "TEST001"
    # 同键覆盖不重复
    await repo.upsert_daily({**doc, "total": 2}, market="CN")
    exact = await repo.get_by_strategy_and_date("CN", "test_strategy", "2026-09-12")
    assert exact["total"] == 2
    latest_any = await repo.get_latest_any("CN")
    assert latest_any is not None
    on_date = await repo.list_strategies_on_date("CN", "2026-09-12")
    assert len(on_date) == 1
    await _cleanup()


async def test_insights_insert_and_quota_count(real_mongo_db):
    await _cleanup()
    repo = ScreeningInsightsRepo()
    today = datetime.now().strftime("%Y-%m-%d")
    await repo.insert_one({"user_id": "test_user_screening", "status": "done",
                           "symbols": ["TEST001"], "insights": {},
                           "created_at": f"{today}T10:00:00"})
    await repo.insert_one({"user_id": "test_user_screening", "status": "failed",
                           "symbols": ["TEST001"], "insights": {},
                           "created_at": f"{today}T11:00:00"})
    n = await repo.count_today_done("test_user_screening", today)
    assert n == 1  # failed 不计数
    await _cleanup()
