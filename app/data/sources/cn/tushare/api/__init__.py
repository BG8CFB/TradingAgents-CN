"""Tushare 独立 API 调用层"""

from .connection import get_tushare_api, TushareConnection

__all__ = ["get_tushare_api", "TushareConnection"]
