"""融资融券仓储。"""

from typing import Dict, List, Optional

from pymongo import UpdateOne

from app.data.storage.mongo.client import get_motor_db
from app.data.storage.mongo.collections import get_collection_name
from app.data.storage.mongo.bulk_utils import batched_bulk_write


class MarginTradingRepo:
    """stock_margin_trading 集合仓储。"""

    async def upsert_many(self, records: List[Dict], market: str) -> int:
        if not records:
            return 0
        db = get_motor_db()
        coll = db[get_collection_name("margin_trading", market)]
        ops = []
        for rec in records:
            sym = rec.get("symbol")
            td = rec.get("trade_date")
            if not sym or not td:
                continue
            ops.append(UpdateOne(
                {"symbol": sym, "trade_date": td},
                {"$set": rec},
                upsert=True,
            ))
        if not ops:
            return 0
        return await batched_bulk_write(coll, ops)

    async def get_by_symbol_and_range(
        self, symbol: str, market: str, start_date: str, end_date: str,
    ) -> List[Dict]:
        db = get_motor_db()
        coll = db[get_collection_name("margin_trading", market)]
        query = {"symbol": symbol, "trade_date": {"$gte": start_date, "$lte": end_date}}
        cursor = coll.find(query, {"_id": 0}).sort("trade_date", -1)
        return await cursor.to_list(length=None)

    async def get_latest_date(self, symbol: str, market: str) -> Optional[str]:
        db = get_motor_db()
        coll = db[get_collection_name("margin_trading", market)]
        doc = await coll.find_one(
            {"symbol": symbol}, {"trade_date": 1}, sort=[("trade_date", -1)]
        )
        return doc["trade_date"] if doc else None
