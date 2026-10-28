import hashlib
from dataclasses import dataclass
from typing import Optional

from app.data.schema.base.common_fields import CommonFields


@dataclass
class StockNewsSchema(CommonFields):
    """新闻公告。"""

    title: Optional[str] = None
    content: Optional[str] = None
    content_hash: Optional[str] = None  # 内容哈希去重（含 symbol）
    source: Optional[str] = None        # 新闻来源
    author: Optional[str] = None
    publish_time: Optional[str] = None
    url: Optional[str] = None
    category: Optional[str] = None
    type: Optional[str] = None          # 语料类型（news/announcement/flash…，向量检索过滤用）
    summary: Optional[str] = None       # 摘要（无正文时兜底展示）
    keywords: Optional[str] = None

    @staticmethod
    def compute_hash(title: str, publish_time: str, symbol: str) -> str:
        """计算内容哈希用于去重。

        symbol 参与哈希：同一篇文章挂多个标的时各自成档，
        不会在 upsert 时互相覆盖 symbol 字段。
        """
        raw = f"{symbol}|{title}|{publish_time}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()
