"""Tushare CN 数据源。"""

from .adapter import TushareCNAdapter
from .provider import TushareCNProvider

__all__ = ["TushareCNAdapter", "TushareCNProvider"]


def get_tushare_adapter():
    return TushareCNAdapter()


def get_tushare_provider():
    return TushareCNProvider()
