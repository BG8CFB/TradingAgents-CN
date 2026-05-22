"""新闻公告仓储。"""

from typing import Dict, List

from pymongo import UpdateOne

from app.data.storage.mongo.client import get_motor_db
from app.data.storage.mongo.collections import get_collection_name


class NewsRepo:

    async def upsert_many(self, records: List[Dict], market: str) -> int:
        if not records:
            return 0
        db = get_motor_db()
        coll = db[get_collection_name("news", market)]
        ops = []
        for rec in records:
            ch = rec.get("content_hash")
            if not ch:
                continue
            ops.append(UpdateOne(
                {"content_hash": ch}, {"$set": rec}, upsert=True
            ))
        if not ops:
            return 0
        result = await coll.bulk_write(ops, ordered=False)
        return result.upserted_count + result.modified_count

    async def get_by_symbol(
        self, symbol: str, market: str, limit: int = 20
    ) -> List[Dict]:
        db = get_motor_db()
        coll = db[get_collection_name("news", market)]
        cursor = coll.find(
            {"symbol": symbol}, {"_id": 0}
        ).sort("publish_time", -1).limit(limit)
        return await cursor.to_list(length=None)
