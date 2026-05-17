"""AKShare 数据源"""

from .adapter import AKShareAdapter
from .provider import AKShareSourceProvider

_akshare_adapter = None


def get_akshare_adapter() -> AKShareAdapter:
    global _akshare_adapter
    if _akshare_adapter is None:
        provider = AKShareSourceProvider()
        _akshare_adapter = AKShareAdapter(provider, market="CN", source_name="akshare")
    return _akshare_adapter


__all__ = ["AKShareAdapter", "get_akshare_adapter"]
