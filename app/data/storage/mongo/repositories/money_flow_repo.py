"""资金流向仓储。"""

from app.data.storage.mongo.repositories.base import MongoBaseRepo


class MoneyFlowRepo(MongoBaseRepo):
    """stock_money_flow 集合仓储。"""

    domain = "money_flow"
    range_sort_direction = -1  # 降序（最新优先），资金流展示类消费方依赖此序
