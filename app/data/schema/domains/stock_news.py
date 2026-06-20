import hashlib
from dataclasses import dataclass
from typing import Optional

from app.data.schema.base.common_fields import CommonFields


@dataclass
class StockNewsSchema(CommonFields):
    """新闻公告。"""

    title: Optional[str] = None
    content: Optional[str] = None
    content_hash: Optional[str] = None  # 内容哈希去重
    source: Optional[str] = None        # 新闻来源
    author: Optional[str] = None
    publish_time: Optional[str] = None
    url: Optional[str] = None
    category: Optional[str] = None
    sentiment: Optional[str] = None
    importance: Optional[int] = None    # 1-5
    keywords: Optional[str] = None

    @staticmethod
    def compute_hash(title: str, publish_time: str) -> str:
        """计算内容哈希用于去重。"""
        raw = f"{title}|{publish_time}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()
