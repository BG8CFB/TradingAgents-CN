"""财务数据仓储。"""

from typing import Dict, List, Optional

from pymongo import UpdateOne

from app.data.storage.mongo.client import get_motor_db
from app.data.storage.mongo.collections import get_collection_name


class FinancialDataRepo:

    async def upsert_many(self, records: List[Dict], market: str) -> int:
        if not records:
            return 0
        db = get_motor_db()
        coll = db[get_collection_name("financial_data", market)]
        ops = []
        for rec in records:
            sym = rec.get("symbol")
            rp = rec.get("report_period")
            st = rec.get("statement_type")
            if not sym or not rp or not st:
                continue
            ops.append(UpdateOne(
                {"symbol": sym, "report_period": rp, "statement_type": st},
                {"$set": rec},
                upsert=True,
            ))
        if not ops:
            return 0
        result = await coll.bulk_write(ops, ordered=False)
        return result.upserted_count + result.modified_count

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
