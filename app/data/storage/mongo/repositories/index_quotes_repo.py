"""指数日线仓储（基准宇宙，symbol 为指数规范码）。"""

from typing import Dict, Optional, Tuple

from app.data.storage.mongo.repositories.base import MongoBaseRepo


class IndexQuotesRepo(MongoBaseRepo):
    """index_daily_quotes 集合仓储。"""

    domain = "index_quotes"
    range_sort_direction = 1  # 升序（时间自然序），基准走势/回撤类消费方按序遍历

    async def get_asof_bar(
        self, symbol: str, market: str, on_date: str
    ) -> Optional[Tuple[str, Dict]]:
        """<= on_date 的最近一个指数 bar（基准 asof 定价：当日缺 bar 退化为前收）。

        Returns:
            (trade_date, bar) 或 None（该日之前无任何数据）。
        """
        coll = self._coll(market)
        doc = await coll.find_one(
            {"symbol": symbol, "trade_date": {"$lte": on_date}},
            {"_id": 0},
            sort=[("trade_date", -1)],
        )
        if not doc or doc.get("trade_date") is None:
            return None
        return doc["trade_date"], doc
