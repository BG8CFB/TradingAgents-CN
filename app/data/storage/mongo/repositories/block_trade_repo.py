"""大宗交易仓储。"""

from typing import Dict, List

from pymongo import UpdateOne

from app.data.storage.mongo.client import get_motor_db
from app.data.storage.mongo.collections import get_collection_name


class BlockTradeRepo:
    """stock_block_trade 集合仓储。"""

    async def upsert_many(self, records: List[Dict], market: str) -> int:
        if not records:
            return 0
        db = get_motor_db()
        coll = db[get_collection_name("block_trade", market)]
        ops = []
        for rec in records:
            sym = rec.get("symbol")
            td = rec.get("trade_date")
            price = rec.get("price")
            vol = rec.get("volume")
            if not sym or not td:
                continue
            ops.append(UpdateOne(
                {"symbol": sym, "trade_date": td, "price": price, "volume": vol},
                {"$set": rec},
                upsert=True,
            ))
        if not ops:
            return 0
        result = await coll.bulk_write(ops, ordered=False)
        return result.upserted_count + result.modified_count

    async def get_by_symbol(
        self, symbol: str, market: str, limit: int = 50
    ) -> List[Dict]:
        db = get_motor_db()
        coll = db[get_collection_name("block_trade", market)]
        cursor = coll.find(
            {"symbol": symbol}, {"_id": 0}
        ).sort("trade_date", -1).limit(limit)
        return await cursor.to_list(length=None)

    async def get_by_date_range(
        self, market: str, start_date: str, end_date: str, limit: int = 100
    ) -> List[Dict]:
        db = get_motor_db()
        coll = db[get_collection_name("block_trade", market)]
        query = {"trade_date": {"$gte": start_date, "$lte": end_date}}
        cursor = coll.find(query, {"_id": 0}).sort("trade_date", -1).limit(limit)
        return await cursor.to_list(length=None)
