"""数据域 Schema 定义。"""

from app.data.schema.domains.basic_info import StockBasicInfoSchema as StockBasicInfoSchema
from app.data.schema.domains.trade_calendar import TradeCalendarSchema as TradeCalendarSchema
from app.data.schema.domains.daily_quotes import DailyQuotesSchema as DailyQuotesSchema
from app.data.schema.domains.daily_indicators import DailyIndicatorsSchema as DailyIndicatorsSchema
from app.data.schema.domains.adj_factors import AdjFactorsSchema as AdjFactorsSchema
from app.data.schema.domains.corporate_actions import CorporateActionsSchema as CorporateActionsSchema
from app.data.schema.domains.financial_data import FinancialDataSchema as FinancialDataSchema
from app.data.schema.domains.market_quotes import MarketQuotesSchema as MarketQuotesSchema
from app.data.schema.domains.stock_news import StockNewsSchema as StockNewsSchema
from app.data.schema.domains.metadata import (
    SyncCheckpointSchema as SyncCheckpointSchema,
    SyncEventSchema as SyncEventSchema,
    SourceHealthSchema as SourceHealthSchema,
)
from app.data.schema.domains.money_flow import MoneyFlowSchema as MoneyFlowSchema
from app.data.schema.domains.margin_trading import MarginTradingSchema as MarginTradingSchema
from app.data.schema.domains.dragon_tiger import DragonTigerSchema as DragonTigerSchema
from app.data.schema.domains.block_trade import BlockTradeSchema as BlockTradeSchema
from app.data.schema.domains.intraday_quotes import IntradayQuotesSchema as IntradayQuotesSchema
