"""指数日线仓储（基准宇宙，symbol 为指数规范码）。"""

from typing import Dict, List, Optional, Tuple

from pymongo import UpdateOne

from app.data.storage.mongo.client import get_motor_db
from app.data.storage.mongo.collections import get_collection_name
from app.data.storage.mongo.bulk_utils import batched_bulk_write
from app.data.storage.mongo.repositories.key_spec import build_filter


class IndexQuotesRepo:
    """index_daily_quotes 集合仓储。"""

    async def upsert_many(self, records: List[Dict], market: str) -> int:
        if not records:
            return 0
        db = get_motor_db()
        coll = db[get_collection_name("index_quotes", market)]
        ops = []
        for rec in records:
            try:
                filter_doc = build_filter("index_quotes", rec)
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
        self, symbol: str, market: str, start_date: str, end_date: str
    ) -> List[Dict]:
        db = get_motor_db()
        coll = db[get_collection_name("index_quotes", market)]
        cursor = coll.find(
            {"symbol": symbol, "trade_date": {"$gte": start_date, "$lte": end_date}},
            {"_id": 0},
        ).sort("trade_date", 1)
        return await cursor.to_list(length=None)

    async def get_asof_bar(
        self, symbol: str, market: str, on_date: str
    ) -> Optional[Tuple[str, Dict]]:
        """<= on_date 的最近一个指数 bar（基准 asof 定价：当日缺 bar 退化为前收）。

        Returns:
            (trade_date, bar) 或 None（该日之前无任何数据）。
        """
        db = get_motor_db()
        coll = db[get_collection_name("index_quotes", market)]
        doc = await coll.find_one(
            {"symbol": symbol, "trade_date": {"$lte": on_date}},
            {"_id": 0},
            sort=[("trade_date", -1)],
        )
        if not doc or doc.get("trade_date") is None:
            return None
        return doc["trade_date"], doc

    async def get_latest_date(self, symbol: str, market: str) -> Optional[str]:
        db = get_motor_db()
        coll = db[get_collection_name("index_quotes", market)]
        doc = await coll.find_one(
            {"symbol": symbol}, {"trade_date": 1}, sort=[("trade_date", -1)]
        )
        return doc["trade_date"] if doc else None
