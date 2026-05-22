"""公共字段 mixin — 每个业务集合必须包含的字段。"""

from dataclasses import dataclass, fields
from datetime import datetime, timezone
from typing import Any, Dict, Optional


@dataclass
class CommonFields:
    """所有业务集合的公共字段基类。子类通过 @dataclass 继承。"""

    symbol: str
    market: str  # CN / HK / US
    data_source: str  # tushare / akshare / baostock / ...
    updated_at: Optional[str] = None  # ISO 8601 UTC

    def to_db_doc(self) -> Dict[str, Any]:
        """转为 MongoDB 文档，过滤 None 值。"""
        doc = {}
        for f in fields(self):
            val = getattr(self, f.name)
            if val is not None:
                doc[f.name] = val
        if "updated_at" not in doc or doc["updated_at"] is None:
            doc["updated_at"] = datetime.now(timezone.utc).isoformat()
        return doc

    @staticmethod
    def now_utc() -> str:
        return datetime.now(timezone.utc).isoformat()
