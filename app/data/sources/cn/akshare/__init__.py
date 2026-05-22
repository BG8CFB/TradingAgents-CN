"""AKShare CN 数据源。"""

from .adapter import AKShareCNAdapter
from .provider import AKShareCNProvider

__all__ = ["AKShareCNAdapter", "AKShareCNProvider"]


def get_akshare_adapter():
    return AKShareCNAdapter()
