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
            filter_doc = {"symbol": sym}
            update_doc = {"$set": rec}
            new_updated = rec.get("last_updated")
            if new_updated:
                # 使用 $max 将 last_updated 比较下推到 MongoDB 服务端：
                # 仅当新值 > 已有值时才更新 last_updated，同时用 $set 覆盖其他字段。
                update_doc = {
                    "$set": {k: v for k, v in rec.items() if k != "last_updated"},
                    "$max": {"last_updated": new_updated},
                }
            ops.append(UpdateOne(filter_doc, update_doc, upsert=True))
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
