"""公共字段 mixin — 每个业务集合必须包含的字段。"""

import math
from dataclasses import dataclass, fields
from datetime import datetime, timezone
from typing import Any, Dict, Optional


def _is_nan_like(value: Any) -> bool:
    """识别 float NaN/Inf 以及 pandas/numpy 的缺失值。

    这些值无法被 JSON 标准序列化（"Out of range float values are not JSON compliant"），
    也无业务含义，统一在写入 MongoDB 前剔除，避免读取端序列化失败。
    """
    if isinstance(value, float):
        try:
            return math.isnan(value) or math.isinf(value)
        except (TypeError, ValueError):
            return False
    # pandas NaN / numpy NaN 通过字符串名称识别，避免硬依赖
    tname = type(value).__name__
    if value is None:
        return False
    if tname == "float" and hasattr(value, "__float__"):
        try:
            f = float(value)
            return math.isnan(f) or math.isinf(f)
        except (TypeError, ValueError):
            return False
    return False


@dataclass
class CommonFields:
    """所有业务集合的公共字段基类。子类通过 @dataclass 继承。"""

    symbol: str
    market: str  # CN / HK / US
    data_source: str  # tushare / akshare / baostock / ...
    updated_at: Optional[str] = None  # ISO 8601 UTC

    def to_db_doc(self) -> Dict[str, Any]:
        """转为 MongoDB 文档，过滤 None 与 NaN/Inf 值。

        NaN/Inf 过滤是为了防止 pandas 缺失值（如 industry 字段为 NaN）
        被写入 BSON 后，读取端 JSON 序列化抛出 ValueError。
        """
        doc = {}
        for f in fields(self):
            val = getattr(self, f.name)
            if val is None:
                continue
            if _is_nan_like(val):
                continue
            doc[f.name] = val
        if "updated_at" not in doc or doc["updated_at"] is None:
            doc["updated_at"] = datetime.now(timezone.utc).isoformat()
        return doc

    @staticmethod
    def now_utc() -> str:
        return datetime.now(timezone.utc).isoformat()
