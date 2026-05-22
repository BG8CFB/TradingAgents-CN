"""美股 Finnhub 数据源。"""

from .adapter import FinnhubUSAdapter
from .provider import FinnhubUSProvider

__all__ = ["FinnhubUSAdapter", "FinnhubUSProvider"]


def get_finnhub_us_adapter():
    return FinnhubUSAdapter()
