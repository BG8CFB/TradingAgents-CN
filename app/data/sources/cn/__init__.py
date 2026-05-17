"""
A股数据源入口
"""


def get_cn_adapter(source_name: str):
    """获取 A 股数据源的 Adapter 实例"""
    if source_name == "tushare":
        from .tushare import get_tushare_adapter
        return get_tushare_adapter()
    elif source_name in ("akshare", "ak"):
        from .akshare import get_akshare_adapter
        return get_akshare_adapter()
    elif source_name in ("baostock", "bst"):
        from .baostock import get_baostock_adapter
        return get_baostock_adapter()
    else:
        raise ValueError(f"不支持的 A 股数据源: {source_name}")
