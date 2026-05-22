"""Tencent HK API 调用层 — 腾讯行情接口 (http://qt.gtimg.cn/q=)，GBK 编码。"""

from .market_quotes import fetch_market_quotes

__all__ = ["fetch_market_quotes"]
