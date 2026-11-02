"""南向资金持仓仓储。"""

from typing import Optional

from app.data.storage.mongo.repositories.base import MongoBaseRepo


class SouthboundHoldingRepo(MongoBaseRepo):

    domain = "southbound_holding"
    range_sort_direction = -1  # 降序（最新优先），持仓变动展示类消费方依赖此序

    async def get_latest_date(self, symbol: str, market: str) -> Optional[str]:
        # 与基类的差异仅投影多剔除 _id、取值用 .get，返回语义一致；保留原实现
        coll = self._coll(market)
        doc = await coll.find_one(
            {"symbol": symbol},
            {"trade_date": 1, "_id": 0},
            sort=[("trade_date", -1)],
        )
        return doc.get("trade_date") if doc else None
