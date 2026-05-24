"""数据域枚举与语义类型。"""

from enum import Enum


class DataDomain(str, Enum):
    BASIC_INFO = "basic_info"
    TRADE_CALENDAR = "trade_calendar"
    DAILY_QUOTES = "daily_quotes"
    DAILY_INDICATORS = "daily_indicators"
    ADJ_FACTORS = "adj_factors"
    CORPORATE_ACTIONS = "corporate_actions"
    FINANCIAL_DATA = "financial_data"
    MARKET_QUOTES = "market_quotes"
    NEWS = "news"
    CONNECT_STATUS = "connect_status"
    SOUTHBOUND_HOLDING = "southbound_holding"
    TUSHARE_UNIVERSE = "tushare_universe"
    PRE_POST_MARKET = "pre_post_market"
    INTRADAY_QUOTES = "intraday_quotes"
    MONEY_FLOW = "money_flow"
    MARGIN_TRADING = "margin_trading"
    DRAGON_TIGER = "dragon_tiger"
    BLOCK_TRADE = "block_trade"


class SemanticType(str, Enum):
    ENTITY = "entity"          # 实体数据（缓慢变化）
    TIMESERIES = "timeseries"  # 时序数据（每日追加）
    SNAPSHOT = "snapshot"      # 快照数据（覆盖更新）
    EVENT = "event"            # 事件数据（追加去重）
    METADATA = "metadata"      # 元数据


DOMAIN_SEMANTIC_TYPE = {
    DataDomain.BASIC_INFO: SemanticType.ENTITY,
    DataDomain.TRADE_CALENDAR: SemanticType.ENTITY,
    DataDomain.DAILY_QUOTES: SemanticType.TIMESERIES,
    DataDomain.DAILY_INDICATORS: SemanticType.TIMESERIES,
    DataDomain.ADJ_FACTORS: SemanticType.TIMESERIES,
    DataDomain.CORPORATE_ACTIONS: SemanticType.TIMESERIES,
    DataDomain.FINANCIAL_DATA: SemanticType.SNAPSHOT,
    DataDomain.MARKET_QUOTES: SemanticType.SNAPSHOT,
    DataDomain.NEWS: SemanticType.EVENT,
    DataDomain.CONNECT_STATUS: SemanticType.ENTITY,
    DataDomain.SOUTHBOUND_HOLDING: SemanticType.TIMESERIES,
    DataDomain.TUSHARE_UNIVERSE: SemanticType.ENTITY,
    DataDomain.PRE_POST_MARKET: SemanticType.SNAPSHOT,
    DataDomain.INTRADAY_QUOTES: SemanticType.TIMESERIES,
    DataDomain.MONEY_FLOW: SemanticType.TIMESERIES,
    DataDomain.MARGIN_TRADING: SemanticType.TIMESERIES,
    DataDomain.DRAGON_TIGER: SemanticType.EVENT,
    DataDomain.BLOCK_TRADE: SemanticType.EVENT,
}

# 行情类数据域（非交易日跳过）
MARKET_DATA_DOMAINS = {
    DataDomain.DAILY_QUOTES,
    DataDomain.DAILY_INDICATORS,
    DataDomain.ADJ_FACTORS,
    DataDomain.MARKET_QUOTES,
    DataDomain.SOUTHBOUND_HOLDING,
    DataDomain.PRE_POST_MARKET,
    DataDomain.INTRADAY_QUOTES,
    DataDomain.MONEY_FLOW,
    DataDomain.MARGIN_TRADING,
    DataDomain.DRAGON_TIGER,
    DataDomain.BLOCK_TRADE,
}
