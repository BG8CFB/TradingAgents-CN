"""Alpha Vantage US 独立 API 调用层。

免费层 25 次/天。
API Key: ALPHA_VANTAGE_API_KEY。
Base URL: https://www.alphavantage.co/query
"""

from .daily_quotes import fetch_daily_quotes
from .financials import fetch_financials

__all__ = [
    "fetch_daily_quotes",
    "fetch_financials",
]
