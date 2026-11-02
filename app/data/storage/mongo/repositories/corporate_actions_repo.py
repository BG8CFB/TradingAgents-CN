"""公司行为仓储 — 仅 HK/US 市场。"""

from typing import Dict, List

from app.data.storage.mongo.repositories.base import MongoBaseRepo


class CorporateActionsRepo(MongoBaseRepo):

    domain = "corporate_actions"

    async def get_by_symbol_and_range(
        self, symbol: str, market: str, start_date: str, end_date: str
    ) -> List[Dict]:
        # 专有变体：区间字段是 ex_date（非 trade_date），与基类模板不同构
        coll = self._coll(market)
        cursor = coll.find(
            {"symbol": symbol, "ex_date": {"$gte": start_date, "$lte": end_date}},
            {"_id": 0},
        ).sort("ex_date", -1)
        return await cursor.to_list(length=None)
