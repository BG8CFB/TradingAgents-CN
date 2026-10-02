"""每日推荐仓储 — 每策略每日一条，job 覆盖写入。"""

from typing import Dict, Optional

from app.data.storage.mongo.client import get_motor_db
from app.data.storage.mongo.collections import get_collection_name
from app.data.storage.mongo.repositories.key_spec import build_filter


class ScreeningRecommendationsRepo:

    async def upsert_daily(self, doc: Dict, market: str) -> None:
        db = get_motor_db()
        coll = db[get_collection_name("screening_recommendations", market)]
        filter_doc = build_filter("screening_recommendations", doc)
        await coll.update_one(filter_doc, {"$set": doc}, upsert=True)

    async def get_latest_by_strategy(self, market: str,
                                     strategy_id: str) -> Optional[Dict]:
        db = get_motor_db()
        coll = db[get_collection_name("screening_recommendations", market)]
        return await coll.find_one(
            {"strategy_id": strategy_id}, {"_id": 0},
            sort=[("trade_date", -1)],
        )

    async def get_by_strategy_and_date(self, market: str, strategy_id: str,
                                       trade_date: str) -> Optional[Dict]:
        db = get_motor_db()
        coll = db[get_collection_name("screening_recommendations", market)]
        return await coll.find_one(
            {"strategy_id": strategy_id, "trade_date": trade_date}, {"_id": 0}
        )

    async def get_latest_any(self, market: str) -> Optional[Dict]:
        db = get_motor_db()
        coll = db[get_collection_name("screening_recommendations", market)]
        return await coll.find_one({}, {"_id": 0}, sort=[("trade_date", -1)])

    async def list_strategies_on_date(self, market: str,
                                      trade_date: str) -> list:
        db = get_motor_db()
        coll = db[get_collection_name("screening_recommendations", market)]
        cursor = coll.find({"trade_date": trade_date}, {"_id": 0})
        return await cursor.to_list(length=None)
