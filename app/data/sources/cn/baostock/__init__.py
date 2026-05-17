"""BaoStock 数据源"""

from .adapter import BaoStockAdapter
from .provider import BaoStockSourceProvider

_baostock_adapter = None


def get_baostock_adapter() -> BaoStockAdapter:
    global _baostock_adapter
    if _baostock_adapter is None:
        provider = BaoStockSourceProvider()
        _baostock_adapter = BaoStockAdapter(provider, market="CN", source_name="baostock")
    return _baostock_adapter


__all__ = ["BaoStockAdapter", "get_baostock_adapter"]
