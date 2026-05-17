"""
港股 AKShare 数据源

provider: 包装现有 improved_hk 模块
adapter: 原始数据 → Schema 标准格式
"""

from .adapter import AKShareHKAdapter

_adapter = None


def get_akshare_hk_adapter() -> AKShareHKAdapter:
    global _adapter
    if _adapter is None:
        from .provider import AKShareHKProvider
        _adapter = AKShareHKAdapter(AKShareHKProvider(), market="HK", source_name="akshare_hk")
    return _adapter
