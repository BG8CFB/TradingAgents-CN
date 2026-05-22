"""Tushare US 独立 API 调用层。

独立 Token (TUSHARE_US_TOKEN)，积分门槛 ≥ 120。
仅覆盖主要美股 + 中概股。
"""

from .us_basic import fetch_stock_list
from .us_tradecal import fetch_trade_calendar
from .us_daily import fetch_daily_quotes
from .us_daily_adj import fetch_daily_adj
from .us_adjfactor import fetch_adj_factors
from .us_financials import fetch_financial_data
from .us_fina_indicator import fetch_fina_indicator

__all__ = [
    "fetch_stock_list",
    "fetch_trade_calendar",
    "fetch_daily_quotes",
    "fetch_daily_adj",
    "fetch_adj_factors",
    "fetch_financial_data",
    "fetch_fina_indicator",
]
