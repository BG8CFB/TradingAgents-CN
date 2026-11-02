"""大宗交易仓储。"""

from typing import Dict, List

from app.data.storage.mongo.repositories.base import MongoBaseRepo


class BlockTradeRepo(MongoBaseRepo):
    """stock_block_trade 集合仓储。"""

    domain = "block_trade"

    async def get_by_symbol(
        self, symbol: str, market: str, limit: int = 50
    ) -> List[Dict]:
        coll = self._coll(market)
        cursor = coll.find(
            {"symbol": symbol}, {"_id": 0}
        ).sort("trade_date", -1).limit(limit)
        return await cursor.to_list(length=None)

    async def get_by_date_range(
        self, market: str, start_date: str, end_date: str, limit: int = 100
    ) -> List[Dict]:
        coll = self._coll(market)
        query = {"trade_date": {"$gte": start_date, "$lte": end_date}}
        cursor = coll.find(query, {"_id": 0}).sort("trade_date", -1).limit(limit)
        return await cursor.to_list(length=None)
