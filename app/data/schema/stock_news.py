"""
stock_news / stock_news_hk / stock_news_us 集合的标准化 Schema

主键: (url, title, publish_time)
"""

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from .base import BaseSchema, get_full_symbol


@dataclass
class NewsSchema(BaseSchema):
    """新闻数据标准 Schema"""

    symbol: Optional[str] = None
    full_symbol: Optional[str] = None
    symbols: Optional[List[str]] = None     # 关联的多只股票

    title: str = ""
    content: Optional[str] = None
    summary: Optional[str] = None
    url: str = ""
    source: Optional[str] = None            # 新闻来源（如 "东方财富"）
    author: Optional[str] = None
    publish_time: Optional[str] = None      # ISO datetime

    category: Optional[str] = None          # "general"/"earnings"/"macro" 等
    sentiment: Optional[str] = None         # "positive"/"negative"/"neutral"
    importance: Optional[str] = None        # "high"/"medium"/"low"
    keywords: Optional[List[str]] = None

    created_at: str = ""

    @classmethod
    def from_raw(cls, raw: Dict[str, Any], source: str, market: str = "CN") -> "NewsSchema":
        """从数据源原始数据构造"""
        symbol = raw.get("symbol")
        full_symbol = None
        if symbol:
            full_symbol = raw.get("full_symbol") or get_full_symbol(symbol, market)

        return cls(
            symbol=symbol,
            full_symbol=full_symbol,
            symbols=raw.get("symbols"),
            title=raw.get("title", ""),
            content=raw.get("content"),
            summary=raw.get("summary"),
            url=raw.get("url", ""),
            source=raw.get("source"),
            author=raw.get("author"),
            publish_time=raw.get("publish_time"),
            category=raw.get("category"),
            sentiment=raw.get("sentiment"),
            importance=raw.get("importance"),
            keywords=raw.get("keywords"),
            data_source=source,
            created_at=raw.get("created_at", ""),
            updated_at=raw.get("updated_at", ""),
        )
