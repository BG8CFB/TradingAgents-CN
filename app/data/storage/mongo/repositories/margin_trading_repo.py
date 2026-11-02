"""融资融券仓储。"""

from app.data.storage.mongo.repositories.base import MongoBaseRepo


class MarginTradingRepo(MongoBaseRepo):
    """stock_margin_trading 集合仓储。"""

    domain = "margin_trading"
    range_sort_direction = -1  # 降序（最新优先），两融展示类消费方依赖此序
