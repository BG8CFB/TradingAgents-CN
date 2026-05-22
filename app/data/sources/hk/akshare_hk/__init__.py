"""港股 AKShare 数据源。"""

from .adapter import AKShareHKAdapter
from .provider import AKShareHKProvider

__all__ = ["AKShareHKAdapter", "AKShareHKProvider"]


def get_akshare_hk_adapter():
    return AKShareHKAdapter()
