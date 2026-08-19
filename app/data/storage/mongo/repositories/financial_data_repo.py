"""财务数据仓储。"""

from typing import Dict, List, Optional

from pymongo import UpdateOne

from app.data.storage.mongo.client import get_motor_db
from app.data.storage.mongo.collections import get_collection_name
from app.data.storage.mongo.bulk_utils import batched_bulk_write
from app.data.storage.mongo.repositories.key_spec import build_filter


class FinancialDataRepo:

    async def upsert_many(self, records: List[Dict], market: str) -> int:
        if not records:
            return 0
        db = get_motor_db()
        coll = db[get_collection_name("financial_data", market)]
        ops = []
        for rec in records:
            try:
                filter_doc = build_filter("financial_data", rec)
            except KeyError:
                continue  # 缺少唯一键字段的记录跳过
            ops.append(UpdateOne(
                filter_doc,
                {"$set": rec},
                upsert=True,
            ))
        if not ops:
            return 0
        return await batched_bulk_write(coll, ops)

    async def get_by_symbol(
        self, symbol: str, market: str, statement_type: Optional[str] = None, limit: int = 20
    ) -> List[Dict]:
        db = get_motor_db()
        coll = db[get_collection_name("financial_data", market)]
        query = {"symbol": symbol}
        if statement_type:
            query["statement_type"] = statement_type
        cursor = coll.find(query, {"_id": 0}).sort("report_period", -1).limit(limit)
        return await cursor.to_list(length=None)
