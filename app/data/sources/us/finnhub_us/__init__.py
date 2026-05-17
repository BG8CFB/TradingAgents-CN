"""
美股 Finnhub 数据源

provider: 直接调用 finnhub-python 库
adapter: 原始数据 → Schema 标准格式
"""

from .adapter import FinnhubUSAdapter

_adapter = None


def get_finnhub_us_adapter() -> FinnhubUSAdapter:
    global _adapter
    if _adapter is None:
        from .provider import FinnhubUSProvider
        _adapter = FinnhubUSAdapter(
            FinnhubUSProvider(), market="US", source_name="finnhub_us"
        )
    return _adapter
