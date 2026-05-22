"""BaoStock CN 数据源。"""

from .adapter import BaoStockCNAdapter
from .provider import BaoStockCNProvider

__all__ = ["BaoStockCNAdapter", "BaoStockCNProvider"]


def get_baostock_adapter():
    return BaoStockCNAdapter()
