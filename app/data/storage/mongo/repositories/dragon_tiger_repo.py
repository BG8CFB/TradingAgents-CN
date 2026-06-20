"""龙虎榜仓储。"""

from typing import Dict, List

from pymongo import UpdateOne

from app.data.storage.mongo.client import get_motor_db
from app.data.storage.mongo.collections import get_collection_name
from app.data.storage.mongo.bulk_utils import batched_bulk_write


class DragonTigerRepo:
    """stock_dragon_tiger 集合仓储。"""

    async def upsert_many(self, records: List[Dict], market: str) -> int:
        if not records:
            return 0
        db = get_motor_db()
        coll = db[get_collection_name("dragon_tiger", market)]
        ops = []
        for rec in records:
            sym = rec.get("symbol")
            td = rec.get("trade_date")
            ex = rec.get("direction", "")
            if not sym or not td:
                continue
            ops.append(UpdateOne(
                {"symbol": sym, "trade_date": td, "direction": ex, "data_source": rec.get("data_source")},
                {"$set": rec},
                upsert=True,
            ))
        if not ops:
            return 0
        return await batched_bulk_write(coll, ops)

    async def get_by_symbol(
        self, symbol: str, market: str, limit: int = 50
    ) -> List[Dict]:
        db = get_motor_db()
        coll = db[get_collection_name("dragon_tiger", market)]
        cursor = coll.find(
            {"symbol": symbol}, {"_id": 0}
        ).sort("trade_date", -1).limit(limit)
        return await cursor.to_list(length=None)

    async def get_by_date(
        self, trade_date: str, market: str, limit: int = 100
    ) -> List[Dict]:
        db = get_motor_db()
        coll = db[get_collection_name("dragon_tiger", market)]
        cursor = coll.find(
            {"trade_date": trade_date}, {"_id": 0}
        ).sort("trade_date", -1).limit(limit)
        return await cursor.to_list(length=None)
