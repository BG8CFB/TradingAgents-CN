"""分钟级行情仓储。"""

from typing import Dict, List

from pymongo import UpdateOne

from app.data.storage.mongo.client import get_motor_db
from app.data.storage.mongo.collections import get_collection_name
from app.data.storage.mongo.bulk_utils import batched_bulk_write
from app.data.storage.mongo.repositories.key_spec import build_filter


class IntradayQuotesRepo:
    """stock_intraday_quotes 集合仓储。"""

    async def upsert_many(self, records: List[Dict], market: str) -> int:
        if not records:
            return 0
        db = get_motor_db()
        coll = db[get_collection_name("intraday_quotes", market)]
        ops = []
        for rec in records:
            try:
                filter_doc = build_filter("intraday_quotes", rec)
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
