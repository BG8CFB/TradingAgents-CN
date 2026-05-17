"""
统一数据库 Schema 定义

所有数据源写入 MongoDB 的字段格式由本模块统一定义。
下游模块只依赖此 Schema，不感知数据源差异。

集合名映射使用 collections.get_collection_name(market, data_type)。
"""

from .base import (
    MarketType,
    DataPeriod,
    BaseSchema,
    get_full_symbol,
)
from .collections import get_collection_name, COLLECTION_MAP
from .stock_basic_info import StockBasicInfoSchema
from .stock_daily_quotes import StockDailyQuoteSchema
from .market_quotes import MarketQuoteSchema
from .stock_financial_data import FinancialDataSchema
from .stock_news import NewsSchema

__all__ = [
    "MarketType",
    "DataPeriod",
    "BaseSchema",
    "get_full_symbol",
    "get_collection_name",
    "COLLECTION_MAP",
    "StockBasicInfoSchema",
    "StockDailyQuoteSchema",
    "MarketQuoteSchema",
    "FinancialDataSchema",
    "NewsSchema",
]
