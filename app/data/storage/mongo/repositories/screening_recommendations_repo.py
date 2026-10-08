"""每日推荐仓储 — 每策略每日一条，job 覆盖写入。"""

import hashlib
import json
from typing import Dict, Optional

from app.data.storage.mongo.client import get_motor_db
from app.data.storage.mongo.collections import get_collection_name
from app.data.storage.mongo.repositories.key_spec import build_filter


def recommendation_fingerprint(doc: Dict) -> str:
    """Stable candidate content, excluding commentary and generation timestamps."""
    content = {key: doc.get(key) for key in ("strategy_id", "trade_date", "style", "total")}
    content["items"] = [
        {key: value for key, value in item.items() if key != "insight"}
        for item in doc.get("items", [])
    ]
    return hashlib.sha256(json.dumps(content, sort_keys=True, ensure_ascii=False,
                                     allow_nan=False).encode()).hexdigest()


class ScreeningRecommendationsRepo:

    async def upsert_generated(self, doc: Dict, market: str) -> None:
        """Regeneration preserves commentary iff the candidate content is identical.

        Mongo evaluates the preservation branch atomically, so an insight written
        during an unchanged regeneration is not replaced by an earlier read.
        Legacy records without a fingerprint are compared by their actual content.
        """
        coll = get_motor_db()[get_collection_name("screening_recommendations", market)]
        key = build_filter("screening_recommendations", doc)
        fingerprint = recommendation_fingerprint(doc)
        old = await coll.find_one(key, {"_id": 0})
        same = {"$eq": ["$recommendation_fingerprint", {"$literal": fingerprint}]}
        if old and not old.get("recommendation_fingerprint") and recommendation_fingerprint(old) == fingerprint:
            # Exact pre-migration content: strip only the mutable insight text.
            old_items = {"$map": {"input": {"$ifNull": ["$items", []]}, "as": "item",
                "in": {"$arrayToObject": {"$filter": {
                    "input": {"$objectToArray": "$$item"}, "as": "field",
                    "cond": {"$ne": ["$$field.k", "insight"]}}}}}}
            new_items = [{k: v for k, v in item.items() if k != "insight"}
                         for item in doc.get("items", [])]
            same = {"$or": [same, {"$and": [
                {"$eq": [{"$ifNull": ["$recommendation_fingerprint", None]}, None]},
                {"$eq": [old_items, {"$literal": new_items}]},
                {"$eq": ["$style", {"$literal": doc.get("style")}]},
                {"$eq": ["$total", {"$literal": doc.get("total")}]},
            ]}]}
        update = {field: {"$literal": value} for field, value in doc.items()
                  if field not in {"_id", "items", "insight_status"}}
        update.update({
            "items": {"$cond": [same, "$items", {"$literal": doc.get("items", [])}]},
            "insight_status": {"$cond": [same, {"$ifNull": ["$insight_status", "none"]}, "none"]},
            "insight_generated_at": {"$cond": [same, "$insight_generated_at", "$$REMOVE"]},
            "recommendation_fingerprint": {"$literal": fingerprint},
        })
        await coll.update_one(key, [{"$set": update}], upsert=True)

    async def upsert_daily(self, doc: Dict, market: str) -> None:
        db = get_motor_db()
        coll = db[get_collection_name("screening_recommendations", market)]
        filter_doc = build_filter("screening_recommendations", doc)
        await coll.update_one(filter_doc, {"$set": doc}, upsert=True)

    async def claim_insight(self, doc: Dict, market: str) -> bool:
        """Only one invocation may pay for a given recommendation snapshot."""
        coll = get_motor_db()[get_collection_name("screening_recommendations", market)]
        key = build_filter("screening_recommendations", doc)
        key.update({"insight_status": {"$in": [None, "none"]},
                    "recommendation_fingerprint": doc.get("recommendation_fingerprint")})
        result = await coll.update_one(key, {"$set": {"insight_status": "pending"}})
        return result.modified_count == 1

    async def finish_insight(self, doc: Dict, market: str) -> bool:
        """Do not overwrite a newer snapshot if factors changed during model I/O."""
        coll = get_motor_db()[get_collection_name("screening_recommendations", market)]
        key = build_filter("screening_recommendations", doc)
        key.update({"insight_status": "pending",
                    "recommendation_fingerprint": doc.get("recommendation_fingerprint")})
        fields = {key: doc[key] for key in ("items", "insight_status", "insight_generated_at")
                  if key in doc}
        result = await coll.update_one(key, {"$set": fields})
        return result.modified_count == 1

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
