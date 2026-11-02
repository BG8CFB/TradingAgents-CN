"""因子分仓储 — L0 批算结果读写。"""

from typing import Dict, List, Optional

from app.data.storage.mongo.repositories.base import MongoBaseRepo


class FactorScoresRepo(MongoBaseRepo):

    domain = "factor_scores"
    range_sort_direction = -1  # 降序（最新优先），因子快照消费方依赖此序

    async def get_latest_trade_date(self, market: str) -> Optional[str]:
        coll = self._coll(market)
        doc = await coll.find_one({}, {"trade_date": 1, "_id": 0},
                                  sort=[("trade_date", -1)])
        return doc.get("trade_date") if doc else None

    async def get_all_by_date(self, market: str, trade_date: str,
                              projection: Optional[Dict] = None) -> List[Dict]:
        coll = self._coll(market)
        cursor = coll.find({"trade_date": trade_date}, projection or {"_id": 0})
        return await cursor.to_list(length=None)
