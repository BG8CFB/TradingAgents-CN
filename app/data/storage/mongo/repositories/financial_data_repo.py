"""财务数据仓储。"""

from typing import Dict, List, Optional

from app.data.storage.mongo.repositories.base import MongoBaseRepo


class FinancialDataRepo(MongoBaseRepo):

    domain = "financial_data"

    async def get_by_symbol(
        self, symbol: str, market: str, statement_type: Optional[str] = None, limit: int = 20
    ) -> List[Dict]:
        coll = self._coll(market)
        query = {"symbol": symbol}
        if statement_type:
            query["statement_type"] = statement_type
        cursor = coll.find(query, {"_id": 0}).sort("report_period", -1).limit(limit)
        return await cursor.to_list(length=None)
