"""公司行为仓储 — 仅 HK/US 市场。"""

from typing import Dict, List

from pymongo import UpdateOne

from app.data.storage.mongo.client import get_motor_db
from app.data.storage.mongo.collections import get_collection_name
from app.data.storage.mongo.bulk_utils import batched_bulk_write


class CorporateActionsRepo:

    async def upsert_many(self, records: List[Dict], market: str) -> int:
        if not records:
            return 0
        db = get_motor_db()
        coll = db[get_collection_name("corporate_actions", market)]
        ops = []
        for rec in records:
            sym = rec.get("symbol")
            ex = rec.get("ex_date")
            at = rec.get("action_type")
            if not sym or not ex or not at:
                continue
            ops.append(UpdateOne(
                {"symbol": sym, "ex_date": ex, "action_type": at, "data_source": rec.get("data_source")},
                {"$set": rec},
                upsert=True,
            ))
        if not ops:
            return 0
        return await batched_bulk_write(coll, ops)

    async def get_by_symbol_and_range(
        self, symbol: str, market: str, start_date: str, end_date: str
    ) -> List[Dict]:
        db = get_motor_db()
        coll = db[get_collection_name("corporate_actions", market)]
        cursor = coll.find(
            {"symbol": symbol, "ex_date": {"$gte": start_date, "$lte": end_date}},
            {"_id": 0},
        ).sort("ex_date", -1)
        return await cursor.to_list(length=None)
