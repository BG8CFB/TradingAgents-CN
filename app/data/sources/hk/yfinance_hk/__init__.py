"""
港股 yfinance 数据源

provider: 包装现有 hk_stock 模块
adapter: 原始数据 → Schema 标准格式
"""

from .adapter import YFinanceHKAdapter

_adapter = None


def get_yfinance_hk_adapter() -> YFinanceHKAdapter:
    global _adapter
    if _adapter is None:
        from .provider import YFinanceHKProvider
        _adapter = YFinanceHKAdapter(YFinanceHKProvider(), market="HK", source_name="yfinance_hk")
    return _adapter
