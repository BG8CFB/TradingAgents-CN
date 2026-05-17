"""
港股数据源入口
"""


def get_hk_adapter(source_name: str):
    """获取港股数据源的 Adapter 实例"""
    if source_name in ("akshare", "akshare_hk"):
        from .akshare_hk import get_akshare_hk_adapter
        return get_akshare_hk_adapter()
    elif source_name in ("yfinance", "yfinance_hk"):
        from .yfinance_hk import get_yfinance_hk_adapter
        return get_yfinance_hk_adapter()
    else:
        raise ValueError(f"不支持的港股数据源: {source_name}")
