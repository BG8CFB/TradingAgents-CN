"""美股盘前盘后行情仓储。"""

from typing import Dict, List, Optional

from pymongo import UpdateOne

from app.data.storage.mongo.client import get_motor_db
from app.data.storage.mongo.collections import get_collection_name


class PrePostMarketRepo:

    async def upsert_many(self, records: List[Dict], market: str) -> int:
        if not records:
            return 0
        db = get_motor_db()
        coll = db[get_collection_name("pre_post_market", market)]
        ops = []
        for rec in records:
            sym = rec.get("symbol")
            td = rec.get("trade_date")
            session_type = rec.get("session_type", "pre")
            if not sym or not td:
                continue
            ops.append(UpdateOne(
                {"symbol": sym, "trade_date": td, "session_type": session_type},
                {"$set": rec},
                upsert=True,
            ))
        if not ops:
            return 0
        result = await coll.bulk_write(ops, ordered=False)
        return result.upserted_count + result.modified_count

    async def get_by_symbol_and_range(
        self, symbol: str, market: str, start_date: str, end_date: str,
        session_type: Optional[str] = None,
    ) -> List[Dict]:
        db = get_motor_db()
        coll = db[get_collection_name("pre_post_market", market)]
        query: Dict = {"symbol": symbol, "trade_date": {"$gte": start_date, "$lte": end_date}}
        if session_type:
            query["session_type"] = session_type
        cursor = coll.find(query, {"_id": 0}).sort("trade_date", -1)
        return await cursor.to_list(length=None)

    async def get_by_symbol(
        self, symbol: str, market: str, limit: int = 50
    ) -> List[Dict]:
        db = get_motor_db()
        coll = db[get_collection_name("pre_post_market", market)]
        query: Dict = {}
        if symbol:
            query["symbol"] = symbol
        cursor = coll.find(query, {"_id": 0}).sort("trade_date", -1).limit(limit)
        return await cursor.to_list(length=None)
