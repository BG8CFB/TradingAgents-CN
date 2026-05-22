"""市场快照仓储。"""

from typing import Dict, List, Optional

from pymongo import UpdateOne

from app.data.storage.mongo.client import get_motor_db
from app.data.storage.mongo.collections import get_collection_name


class MarketQuotesRepo:

    async def upsert_many(self, records: List[Dict], market: str) -> int:
        if not records:
            return 0
        db = get_motor_db()
        coll = db[get_collection_name("market_quotes", market)]
        ops = []
        for rec in records:
            sym = rec.get("symbol")
            if not sym:
                continue
            # 写入前比较 last_updated，仅当新数据更新时覆盖
            new_updated = rec.get("last_updated")
            existing = await coll.find_one({"symbol": sym}, {"last_updated": 1})
            if existing and existing.get("last_updated") and new_updated:
                if new_updated <= existing["last_updated"]:
                    continue
            ops.append(UpdateOne(
                {"symbol": sym}, {"$set": rec}, upsert=True
            ))
        if not ops:
            return 0
        result = await coll.bulk_write(ops, ordered=False)
        return result.upserted_count + result.modified_count

    async def get_by_symbol(self, symbol: str, market: str) -> Optional[Dict]:
        db = get_motor_db()
        coll = db[get_collection_name("market_quotes", market)]
        return await coll.find_one({"symbol": symbol}, {"_id": 0})

    async def get_all(self, market: str, limit: int = 100) -> List[Dict]:
        db = get_motor_db()
        coll = db[get_collection_name("market_quotes", market)]
        cursor = coll.find({}, {"_id": 0}).limit(limit)
        return await cursor.to_list(length=None)
