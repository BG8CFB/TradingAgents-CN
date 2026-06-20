"""大宗交易仓储。"""

from typing import Dict, List

from pymongo import UpdateOne

from app.data.storage.mongo.client import get_motor_db
from app.data.storage.mongo.collections import get_collection_name
from app.data.storage.mongo.bulk_utils import batched_bulk_write


class BlockTradeRepo:
    """stock_block_trade 集合仓储。"""

    async def upsert_many(self, records: List[Dict], market: str) -> int:
        if not records:
            return 0
        db = get_motor_db()
        coll = db[get_collection_name("block_trade", market)]
        ops = []
        for rec in records:
            sym = rec.get("symbol")
            td = rec.get("trade_date")
            if not sym or not td:
                continue
            # filter 字段与 init_collections.py 的唯一索引保持一致：
            # symbol + trade_date + buyer + seller + data_source
            # （不用浮点 price/volume 做唯一键，避免精度风险；
            #  data_source 区分不同源对同一笔交易的重复采集）
            buyer = rec.get("buyer") or ""
            seller = rec.get("seller") or ""
            ops.append(UpdateOne(
                {
                    "symbol": sym,
                    "trade_date": td,
                    "buyer": buyer,
                    "seller": seller,
                    "data_source": rec.get("data_source"),
                },
                {"$set": rec},
                upsert=True,
            ))
        if not ops:
            return 0
        return await batched_bulk_write(coll, ops)

    async def get_by_symbol(
        self, symbol: str, market: str, limit: int = 50
    ) -> List[Dict]:
        db = get_motor_db()
        coll = db[get_collection_name("block_trade", market)]
        cursor = coll.find(
            {"symbol": symbol}, {"_id": 0}
        ).sort("trade_date", -1).limit(limit)
        return await cursor.to_list(length=None)

    async def get_by_date_range(
        self, market: str, start_date: str, end_date: str, limit: int = 100
    ) -> List[Dict]:
        db = get_motor_db()
        coll = db[get_collection_name("block_trade", market)]
        query = {"trade_date": {"$gte": start_date, "$lte": end_date}}
        cursor = coll.find(query, {"_id": 0}).sort("trade_date", -1).limit(limit)
        return await cursor.to_list(length=None)
