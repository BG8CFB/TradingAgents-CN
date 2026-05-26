"""A 股数据源入口 — Provider/Adapter 工厂 + 能力注册。"""

from typing import Optional

from app.data.sources.base.provider import BaseProvider
from app.data.sources.base.adapter import BaseAdapter


def get_cn_provider(source_name: str) -> Optional[BaseProvider]:
    if source_name == "tushare":
        from .tushare.provider import TushareCNProvider
        return TushareCNProvider()
    elif source_name in ("akshare", "ak"):
        from .akshare.provider import AKShareCNProvider
        return AKShareCNProvider()
    elif source_name in ("baostock", "bst"):
        from .baostock.provider import BaoStockCNProvider
        return BaoStockCNProvider()
    return None


def get_cn_adapter(source_name: str) -> Optional[BaseAdapter]:
    if source_name == "tushare":
        from .tushare.adapter import TushareCNAdapter
        return TushareCNAdapter()
    elif source_name in ("akshare", "ak"):
        from .akshare.adapter import AKShareCNAdapter
        return AKShareCNAdapter()
    elif source_name in ("baostock", "bst"):
        from .baostock.adapter import BaoStockCNAdapter
        return BaoStockCNAdapter()
    return None
