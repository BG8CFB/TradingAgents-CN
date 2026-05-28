"""沪深港通连通状态仓储。"""

from typing import Dict, List, Optional

from pymongo import UpdateOne

from app.data.storage.mongo.client import get_motor_db
from app.data.storage.mongo.collections import get_collection_name
from app.data.storage.mongo.bulk_utils import batched_bulk_write


class ConnectStatusRepo:

    async def upsert_many(self, records: List[Dict], market: str) -> int:
        if not records:
            return 0
        db = get_motor_db()
        coll = db[get_collection_name("connect_status", market)]
        ops = []
        for rec in records:
            trade_date = rec.get("trade_date")
            if not trade_date:
                continue
            ops.append(UpdateOne(
                {"trade_date": trade_date},
                {"$set": rec},
                upsert=True,
            ))
        if not ops:
            return 0
        return await batched_bulk_write(coll, ops)

    async def get_by_date_range(
        self, market: str, start_date: str, end_date: str, limit: int = 100
    ) -> List[Dict]:
        db = get_motor_db()
        coll = db[get_collection_name("connect_status", market)]
        cursor = coll.find(
            {"trade_date": {"$gte": start_date, "$lte": end_date}},
            {"_id": 0},
        ).sort("trade_date", -1).limit(limit)
        return await cursor.to_list(length=None)

    async def get_latest(self, market: str) -> Optional[Dict]:
        db = get_motor_db()
        coll = db[get_collection_name("connect_status", market)]
        return await coll.find_one({"_id": 0}, sort=[("trade_date", -1)])
