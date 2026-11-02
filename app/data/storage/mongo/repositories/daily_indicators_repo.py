"""每日指标仓储。"""

from app.data.storage.mongo.repositories.base import MongoBaseRepo


class DailyIndicatorsRepo(MongoBaseRepo):

    domain = "daily_indicators"
    range_sort_direction = -1  # 降序（最新优先），指标展示类消费方依赖此序
