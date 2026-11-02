"""分钟级行情仓储。"""

from typing import Dict, List

from app.data.storage.mongo.repositories.base import MongoBaseRepo


class IntradayQuotesRepo(MongoBaseRepo):
    """stock_intraday_quotes 集合仓储。"""

    domain = "intraday_quotes"

    async def get_by_symbol_and_range(
        self, symbol: str, market: str, start_datetime: str, end_datetime: str,
        freq: str = None,
    ) -> List[Dict]:
        # 专有变体：区间字段是 datetime（非 trade_date），与基类模板不同构
        coll = self._coll(market)
        query: Dict = {"symbol": symbol, "datetime": {"$gte": start_datetime, "$lte": end_datetime}}
        if freq:
            query["freq"] = freq
        cursor = coll.find(query, {"_id": 0}).sort("datetime", 1)
        return await cursor.to_list(length=None)
