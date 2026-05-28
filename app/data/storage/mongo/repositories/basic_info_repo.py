"""股票基本信息仓储。"""

from typing import Dict, List, Optional

from pymongo import UpdateOne

from app.data.storage.mongo.client import get_motor_db
from app.data.storage.mongo.collections import get_collection_name
from app.data.storage.mongo.bulk_utils import batched_bulk_write


class BasicInfoRepo:
    """stock_basic_info 集合仓储。"""

    async def upsert_many(self, records: List[Dict], market: str) -> int:
        if not records:
            return 0
        db = get_motor_db()
        coll = db[get_collection_name("basic_info", market)]
        ops = []
        for rec in records:
            if "symbol" not in rec:
                continue
            ops.append(UpdateOne(
                {"symbol": rec["symbol"]},
                {"$set": rec},
                upsert=True,
            ))
        if not ops:
            return 0
        return await batched_bulk_write(coll, ops)

    async def get_by_symbol(self, symbol: str, market: str) -> Optional[Dict]:
        db = get_motor_db()
        coll = db[get_collection_name("basic_info", market)]
        return await coll.find_one({"symbol": symbol}, {"_id": 0})

    async def get_all(self, market: str, limit: int = 0) -> List[Dict]:
        db = get_motor_db()
        coll = db[get_collection_name("basic_info", market)]
        cursor = coll.find({}, {"_id": 0})
        if limit > 0:
            cursor = cursor.limit(limit)
        return await cursor.to_list(length=None)

    async def get_active_symbols(self, market: str) -> List[Dict]:
        """获取活跃（未退市）股票的 symbol 列表。"""
        db = get_motor_db()
        coll = db[get_collection_name("basic_info", market)]
        cursor = coll.find(
            {"list_status": "L"},
            {"symbol": 1, "_id": 0},
        )
        return await cursor.to_list(length=None)

    async def count(self, market: str) -> int:
        db = get_motor_db()
        coll = db[get_collection_name("basic_info", market)]
        return await coll.count_documents({})
