"""美股 yfinance 数据源。"""

from .adapter import YFinanceUSAdapter
from .provider import YFinanceUSProvider

__all__ = ["YFinanceUSAdapter", "YFinanceUSProvider"]


def get_yfinance_us_adapter():
    return YFinanceUSAdapter()
