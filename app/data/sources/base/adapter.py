"""BaseAdapter: 数据源标准化转换基类。

职责：将 Provider 返回的原始数据转换为标准 Schema 格式。
负责字段映射、单位转换、空值处理。
不调外部 API、不写数据库。
"""

import logging
from abc import ABC
from typing import Any, List


from app.data.schema.domains.basic_info import StockBasicInfoSchema
from app.data.schema.domains.trade_calendar import TradeCalendarSchema
from app.data.schema.domains.daily_quotes import DailyQuotesSchema
from app.data.schema.domains.daily_indicators import DailyIndicatorsSchema
from app.data.schema.domains.adj_factors import AdjFactorsSchema
from app.data.schema.domains.corporate_actions import CorporateActionsSchema
from app.data.schema.domains.financial_data import FinancialDataSchema
from app.data.schema.domains.market_quotes import MarketQuotesSchema
from app.data.schema.domains.stock_news import StockNewsSchema
from app.data.schema.domains.money_flow import MoneyFlowSchema
from app.data.schema.domains.margin_trading import MarginTradingSchema
from app.data.schema.domains.dragon_tiger import DragonTigerSchema
from app.data.schema.domains.block_trade import BlockTradeSchema
from app.data.schema.domains.intraday_quotes import IntradayQuotesSchema


class BaseAdapter(ABC):
    """数据源标准化转换基类。"""

    def __init__(self, provider, market: str, source_name: str):
        self.provider = provider
        self.market = market
        self.source_name = source_name
        self.logger = logging.getLogger(f"adapter.{market}.{source_name}")

    def adapt_basic_info(self, raw: Any) -> List[StockBasicInfoSchema]:
        """将原始数据转换为 StockBasicInfoSchema 列表。"""
        raise NotImplementedError(f"{self.source_name} 不支持 basic_info")

    def adapt_trade_calendar(self, raw: Any) -> List[TradeCalendarSchema]:
        """将原始数据转换为 TradeCalendarSchema 列表。"""
        raise NotImplementedError(f"{self.source_name} 不支持 trade_calendar")

    def adapt_daily_quotes(self, raw: Any) -> List[DailyQuotesSchema]:
        """将原始数据转换为 DailyQuotesSchema 列表。"""
        raise NotImplementedError(f"{self.source_name} 不支持 daily_quotes")

    def adapt_daily_indicators(self, raw: Any) -> List[DailyIndicatorsSchema]:
        """将原始数据转换为 DailyIndicatorsSchema 列表。"""
        raise NotImplementedError(f"{self.source_name} 不支持 daily_indicators")

    def adapt_financial_data(self, raw: Any) -> List[FinancialDataSchema]:
        """将原始数据转换为 FinancialDataSchema 列表。"""
        raise NotImplementedError(f"{self.source_name} 不支持 financial_data")

    def adapt_adj_factors(self, raw: Any) -> List[AdjFactorsSchema]:
        """将原始数据转换为 AdjFactorsSchema 列表。"""
        raise NotImplementedError(f"{self.source_name} 不支持 adj_factors")

    def adapt_corporate_actions(self, raw: Any) -> List[CorporateActionsSchema]:
        """将原始数据转换为 CorporateActionsSchema 列表。"""
        raise NotImplementedError(f"{self.source_name} 不支持 corporate_actions")

    def adapt_news(self, raw: Any) -> List[StockNewsSchema]:
        """将原始数据转换为 StockNewsSchema 列表。"""
        raise NotImplementedError(f"{self.source_name} 不支持 news")

    def adapt_market_quotes(self, raw: Any) -> List[MarketQuotesSchema]:
        """将原始数据转换为 MarketQuotesSchema 列表。"""
        raise NotImplementedError(f"{self.source_name} 不支持 market_quotes")

    def adapt_intraday_quotes(self, raw: Any) -> List[IntradayQuotesSchema]:
        """将原始数据转换为 IntradayQuotesSchema 列表。"""
        raise NotImplementedError(f"{self.source_name} 不支持 intraday_quotes")

    def adapt_money_flow(self, raw: Any) -> List[MoneyFlowSchema]:
        """将原始数据转换为 MoneyFlowSchema 列表。"""
        raise NotImplementedError(f"{self.source_name} 不支持 money_flow")

    def adapt_margin_trading(self, raw: Any) -> List[MarginTradingSchema]:
        """将原始数据转换为 MarginTradingSchema 列表。"""
        raise NotImplementedError(f"{self.source_name} 不支持 margin_trading")

    def adapt_dragon_tiger(self, raw: Any) -> List[DragonTigerSchema]:
        """将原始数据转换为 DragonTigerSchema 列表。"""
        raise NotImplementedError(f"{self.source_name} 不支持 dragon_tiger")

    def adapt_block_trade(self, raw: Any) -> List[BlockTradeSchema]:
        """将原始数据转换为 BlockTradeSchema 列表。"""
        raise NotImplementedError(f"{self.source_name} 不支持 block_trade")
