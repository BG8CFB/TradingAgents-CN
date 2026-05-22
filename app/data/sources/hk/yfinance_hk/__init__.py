"""港股 yfinance 数据源。"""

from .adapter import YFinanceHKAdapter
from .provider import YFinanceHKProvider

__all__ = ["YFinanceHKAdapter", "YFinanceHKProvider"]


def get_yfinance_hk_adapter():
    return YFinanceHKAdapter()
