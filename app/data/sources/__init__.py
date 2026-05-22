"""
数据源模块

按市场组织：cn/ (A股)、hk/ (港股)、us/ (美股)
每个数据源包含：provider.py (API调用)、adapter.py (标准化转换)、功能编排模块
"""


def get_adapter(market: str, source_name: str):
    """
    获取指定市场和数据源的 Adapter 实例。

    Args:
        market: "CN" / "HK" / "US"
        source_name: "tushare" / "akshare" / "baostock" / "yfinance_hk" / "yfinance" / "finnhub" 等

    Returns:
        Adapter 实例
    """
    if market == "CN":
        from .cn import get_cn_adapter
        return get_cn_adapter(source_name)
    elif market == "HK":
        from .hk import get_hk_adapter
        return get_hk_adapter(source_name)
    elif market == "US":
        from .us import get_us_adapter
        return get_us_adapter(source_name)
    else:
        raise ValueError(f"不支持的市场: {market}")
