"""
美股 yfinance 数据源

provider: 直接调用 yfinance 库
adapter: 原始数据 → Schema 标准格式
"""

from .adapter import YFinanceUSAdapter

_adapter = None


def get_yfinance_us_adapter() -> YFinanceUSAdapter:
    global _adapter
    if _adapter is None:
        from .provider import YFinanceUSProvider
        _adapter = YFinanceUSAdapter(
            YFinanceUSProvider(), market="US", source_name="yfinance_us"
        )
    return _adapter
