"""日线行情仓储。"""

from typing import Dict, List, Optional

from app.data.storage.mongo.repositories.base import MongoBaseRepo


class DailyQuotesRepo(MongoBaseRepo):
    """stock_daily_quotes 集合仓储。"""

    domain = "daily_quotes"
    # 升序（时间自然序）：K线取尾部最新、周期聚合等消费方依赖此序，
    # 展示层的"最新优先"由查看器路由统一处理。
    range_sort_direction = 1

    async def get_by_symbol_and_range(
        self, symbol: str, market: str, start_date: str, end_date: str,
        period: Optional[str] = None,
    ) -> List[Dict]:
        extra_query = {"period": period} if period else None
        return await super().get_by_symbol_and_range(
            symbol, market, start_date, end_date, extra_query=extra_query,
        )
