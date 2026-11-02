"""美股盘前盘后行情仓储。"""

from typing import Dict, List, Optional

from app.data.storage.mongo.repositories.base import MongoBaseRepo


class PrePostMarketRepo(MongoBaseRepo):

    domain = "pre_post_market"
    range_sort_direction = -1  # 降序（最新优先），盘前盘后展示类消费方依赖此序

    async def get_by_symbol_and_range(
        self, symbol: str, market: str, start_date: str, end_date: str,
        session_type: Optional[str] = None,
    ) -> List[Dict]:
        extra_query = {"session_type": session_type} if session_type else None
        return await super().get_by_symbol_and_range(
            symbol, market, start_date, end_date, extra_query=extra_query,
        )

    async def get_by_symbol(
        self, symbol: str, market: str, limit: int = 50
    ) -> List[Dict]:
        coll = self._coll(market)
        query: Dict = {}
        if symbol:
            query["symbol"] = symbol
        cursor = coll.find(query, {"_id": 0}).sort("trade_date", -1).limit(limit)
        return await cursor.to_list(length=None)
