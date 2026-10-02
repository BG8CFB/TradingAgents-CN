"""GET /daily 读取落库推荐（含数据截至标注，经服务层）。"""
import pytest

pytestmark = pytest.mark.requires_db

from app.data.storage.mongo.client import get_motor_db
from app.data.storage.mongo.collections import get_collection_name
from app.data.storage.mongo.repositories.screening_recommendations_repo import (
    ScreeningRecommendationsRepo,
)
from app.services.screening.strategy_service import StrategyService


async def test_daily_read_seeded(real_mongo_db):
    db = get_motor_db()
    coll = db[get_collection_name("screening_recommendations", "CN")]
    await coll.delete_many({"strategy_id": "test_daily"})
    await ScreeningRecommendationsRepo().upsert_daily({
        "strategy_id": "test_daily", "trade_date": "2026-09-11",
        "strategy_name": "测试", "style": "short_term", "total": 1,
        "items": [{"symbol": "TESTD001", "name": "x", "score": 90.0,
                   "factors": {}, "signals": [], "insight": None}],
        "insight_status": "none",
    }, market="CN")

    result = await StrategyService().get_daily("test_daily")
    assert result["trade_date"] == "2026-09-11"
    assert result["strategies"][0]["items"][0]["symbol"] == "TESTD001"

    result_all = await StrategyService().get_daily()
    assert any(s["strategy_id"] == "test_daily" for s in result_all["strategies"])

    await coll.delete_many({"strategy_id": "test_daily"})


async def test_daily_empty_returns_skeleton(real_mongo_db):
    """无落库数据时返回空骨架而非异常（前端空态）。"""
    result = await StrategyService().get_daily("nonexistent_strategy")
    assert result["trade_date"] is None
    assert result["strategies"] == []
