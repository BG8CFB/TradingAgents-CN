"""交易日历仓储。"""

from typing import Dict, List

from pymongo import UpdateOne

from app.data.storage.mongo.client import get_motor_db
from app.data.storage.mongo.collections import get_collection_name


class TradeCalendarRepo:

    async def upsert_many(self, records: List[Dict], market: str) -> int:
        if not records:
            return 0
        db = get_motor_db()
        coll = db[get_collection_name("trade_calendar", market)]
        ops = []
        for rec in records:
            ex = rec.get("exchange")
            cd = rec.get("cal_date")
            if not ex or not cd:
                continue
            ops.append(UpdateOne(
                {"exchange": ex, "cal_date": cd},
                {"$set": rec},
                upsert=True,
            ))
        if not ops:
            return 0
        result = await coll.bulk_write(ops, ordered=False)
        return result.upserted_count + result.modified_count

    async def is_trading_day(self, date: str, exchange: str, market: str) -> bool:
        db = get_motor_db()
        coll = db[get_collection_name("trade_calendar", market)]
        doc = await coll.find_one(
            {"cal_date": date, "exchange": exchange},
            {"is_open": 1},
        )
        return bool(doc and doc.get("is_open"))

    async def get_range(
        self, exchange: str, market: str, start_date: str, end_date: str
    ) -> List[Dict]:
        db = get_motor_db()
        coll = db[get_collection_name("trade_calendar", market)]
        cursor = coll.find(
            {"exchange": exchange, "cal_date": {"$gte": start_date, "$lte": end_date}},
            {"_id": 0},
        ).sort("cal_date", 1)
        return await cursor.to_list(length=None)
