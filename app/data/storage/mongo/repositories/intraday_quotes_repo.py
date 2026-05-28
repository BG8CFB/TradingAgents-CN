"""分钟级行情仓储。"""

from typing import Dict, List

from pymongo import UpdateOne

from app.data.storage.mongo.client import get_motor_db
from app.data.storage.mongo.collections import get_collection_name
from app.data.storage.mongo.bulk_utils import batched_bulk_write


class IntradayQuotesRepo:
    """stock_intraday_quotes 集合仓储。"""

    async def upsert_many(self, records: List[Dict], market: str) -> int:
        if not records:
            return 0
        db = get_motor_db()
        coll = db[get_collection_name("intraday_quotes", market)]
        ops = []
        for rec in records:
            sym = rec.get("symbol")
            dt = rec.get("datetime")
            freq = rec.get("freq", "30min")
            if not sym or not dt:
                continue
            ops.append(UpdateOne(
                {"symbol": sym, "datetime": dt, "freq": freq},
                {"$set": rec},
                upsert=True,
            ))
        if not ops:
            return 0
        return await batched_bulk_write(coll, ops)

    async def get_by_symbol_and_range(
        self, symbol: str, market: str, start_datetime: str, end_datetime: str,
        freq: str = None,
    ) -> List[Dict]:
        db = get_motor_db()
        coll = db[get_collection_name("intraday_quotes", market)]
        query: Dict = {"symbol": symbol, "datetime": {"$gte": start_datetime, "$lte": end_datetime}}
        if freq:
            query["freq"] = freq
        cursor = coll.find(query, {"_id": 0}).sort("datetime", 1)
        return await cursor.to_list(length=None)
