"""复权因子仓储。"""

from app.data.storage.mongo.repositories.base import MongoBaseRepo


class AdjFactorsRepo(MongoBaseRepo):

    domain = "adj_factors"
    range_sort_direction = 1  # 升序（时间自然序），前复权序列计算类消费方依赖此序
