"""
Tushare 数据源

provider: 包装现有 TushareProvider，复用全部 API 调用逻辑
adapter: 原始数据 → Schema 标准格式（字段映射 + 单位转换）
"""

from .adapter import TushareAdapter

_tushare_adapter = None


def get_tushare_adapter() -> TushareAdapter:
    global _tushare_adapter
    if _tushare_adapter is None:
        from .provider import TushareSourceProvider
        provider = TushareSourceProvider()
        _tushare_adapter = TushareAdapter(provider, market="CN", source_name="tushare")
    return _tushare_adapter


__all__ = ["TushareAdapter", "get_tushare_adapter"]
