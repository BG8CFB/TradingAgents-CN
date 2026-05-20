"""A 股域级同步模块"""

from .base_domain_sync import BaseDomainSync
from .basic_info_sync import BasicInfoSync
from .trade_calendar_sync import TradeCalendarSync
from .daily_quotes_sync import DailyQuotesSync
from .daily_indicators_sync import DailyIndicatorsSync
from .adj_factors_sync import AdjFactorsSync
from .financial_data_sync import FinancialDataSync
from .news_sync import NewsSync
from .aggregation_sync import AggregationSync

__all__ = [
    "BaseDomainSync",
    "BasicInfoSync",
    "TradeCalendarSync",
    "DailyQuotesSync",
    "DailyIndicatorsSync",
    "AdjFactorsSync",
    "FinancialDataSync",
    "NewsSync",
    "AggregationSync",
]
