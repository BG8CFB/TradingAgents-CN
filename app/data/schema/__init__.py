"""数据平台 Schema 层 — 统一数据字段定义。

目录结构:
  base/      — 公共类型、枚举、公共字段
  domains/   — 各数据域 Schema 定义（三市场共用字段）
  markets/   — 市场特化字段（cn / hk / us）
"""

# base
from app.data.schema.base.types import DateStr as DateStr
from app.data.schema.base.types import _safe_float as _safe_float, _safe_int as _safe_int, _safe_str as _safe_str, _parse_date as _parse_date
from app.data.schema.base.markets import MarketType as MarketType, MarketMeta as MarketMeta, MARKET_META as MARKET_META
from app.data.schema.base.common_fields import CommonFields as CommonFields
from app.data.schema.base.enums import (
    ListStatus as ListStatus,
    StatementType as StatementType,
    ReportType as ReportType,
    ActionType as ActionType,
    DataPeriod as DataPeriod,
    SupportLevel as SupportLevel,
    CircuitState as CircuitState,
    RefreshStatus as RefreshStatus,
    FreshnessState as FreshnessState,
    QuoteSourceType as QuoteSourceType,
    MarketSession as MarketSession,
)

# domains
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
