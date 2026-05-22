"""Tushare HK API 调用层 — 独立 Token (TUSHARE_HK_TOKEN)，积分门槛 ≥ 2000。"""

from .hk_basic import fetch_stock_list
from .hk_tradecal import fetch_trade_calendar
from .hk_daily import fetch_daily_quotes
from .hk_daily_adj import fetch_daily_adj
from .hk_adjfactor import fetch_adj_factors
from .hk_financials import fetch_financial_data
from .hk_fina_indicator import fetch_fina_indicator
from .hk_hold import fetch_southbound_holdings
from .rt_hk_k import fetch_realtime_quotes

__all__ = [
    "fetch_stock_list",
    "fetch_trade_calendar",
    "fetch_daily_quotes",
    "fetch_daily_adj",
    "fetch_adj_factors",
    "fetch_financial_data",
    "fetch_fina_indicator",
    "fetch_southbound_holdings",
    "fetch_realtime_quotes",
]
