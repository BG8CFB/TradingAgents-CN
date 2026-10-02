"""因子分仓储 — L0 批算结果读写。"""

from typing import Dict, List, Optional

from pymongo import UpdateOne

from app.data.storage.mongo.client import get_motor_db
from app.data.storage.mongo.collections import get_collection_name
from app.data.storage.mongo.bulk_utils import batched_bulk_write
from app.data.storage.mongo.repositories.key_spec import build_filter


class FactorScoresRepo:

    async def upsert_many(self, records: List[Dict], market: str) -> int:
        """按 (symbol, trade_date) 幂等覆盖写入；缺唯一键的记录跳过。"""
        if not records:
            return 0
        db = get_motor_db()
        coll = db[get_collection_name("factor_scores", market)]
        ops = []
        for rec in records:
            try:
                filter_doc = build_filter("factor_scores", rec)
            except KeyError:
                continue
            ops.append(UpdateOne(filter_doc, {"$set": rec}, upsert=True))
        if not ops:
            return 0
        return await batched_bulk_write(coll, ops)

    async def get_by_symbol_and_range(
        self, symbol: str, market: str, start_date: str, end_date: str
    ) -> List[Dict]:
        db = get_motor_db()
        coll = db[get_collection_name("factor_scores", market)]
        cursor = coll.find(
            {"symbol": symbol, "trade_date": {"$gte": start_date, "$lte": end_date}},
            {"_id": 0},
        ).sort("trade_date", -1)
        return await cursor.to_list(length=None)

    async def get_latest_trade_date(self, market: str) -> Optional[str]:
        db = get_motor_db()
        coll = db[get_collection_name("factor_scores", market)]
        doc = await coll.find_one({}, {"trade_date": 1, "_id": 0},
                                  sort=[("trade_date", -1)])
        return doc.get("trade_date") if doc else None

    async def get_all_by_date(self, market: str, trade_date: str,
                              projection: Optional[Dict] = None) -> List[Dict]:
        db = get_motor_db()
        coll = db[get_collection_name("factor_scores", market)]
        cursor = coll.find({"trade_date": trade_date}, projection or {"_id": 0})
        return await cursor.to_list(length=None)
