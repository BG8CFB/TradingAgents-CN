"""沪深港通连通状态仓储。"""

from typing import Dict, List, Optional

from app.data.storage.mongo.repositories.base import MongoBaseRepo


class ConnectStatusRepo(MongoBaseRepo):

    domain = "connect_status"

    async def get_by_date_range(
        self, market: str, start_date: str, end_date: str, limit: int = 100
    ) -> List[Dict]:
        coll = self._coll(market)
        cursor = coll.find(
            {"trade_date": {"$gte": start_date, "$lte": end_date}},
            {"_id": 0},
        ).sort("trade_date", -1).limit(limit)
        return await cursor.to_list(length=None)

    async def get_latest(self, market: str) -> Optional[Dict]:
        coll = self._coll(market)
        return await coll.find_one({}, {"_id": 0}, sort=[("trade_date", -1)])
