"""
Schema 基类、枚举定义、公共工具函数
"""

from dataclasses import dataclass, field, asdict
from datetime import datetime
from enum import Enum
from typing import Any, Dict, Optional

from app.utils.time_utils import now_utc


class MarketType(str, Enum):
    CN = "CN"
    HK = "HK"
    US = "US"


class DataPeriod(str, Enum):
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"


@dataclass
class BaseSchema:
    """Schema 基类：提供 to_db_doc()"""

    data_source: str
    updated_at: str  # ISO format UTC

    def to_db_doc(self) -> Dict[str, Any]:
        """转换为 MongoDB 文档，过滤 None 值"""
        return {k: v for k, v in asdict(self).items()
                if v is not None and not k.startswith("_")}


def get_full_symbol(symbol: str, market: str) -> str:
    """全局唯一的 full_symbol 生成函数。"""
    if not symbol:
        return symbol

    if market == "CN":
        if symbol.startswith(("60", "68", "90")):
            return f"{symbol}.SH"
        elif symbol.startswith(("0", "3", "20")):
            return f"{symbol}.SZ"
        elif symbol.startswith(("4", "8")):
            return f"{symbol}.BJ"
        return f"{symbol}.SZ"
    elif market == "HK":
        return f"{symbol}.HK"
    return symbol


def normalize_symbol(symbol: str, market: str) -> str:
    """统一股票代码格式。

    CN: 6 位数字，如 000001
    HK: 5 位数字（去掉 .HK 后缀），如 00700
    US: 大写 ticker，如 AAPL
    """
    s = str(symbol).strip()
    if market == "CN":
        return s.zfill(6)
    elif market == "HK":
        return s.replace(".HK", "").lstrip("0").zfill(5)
    else:
        return s.upper()


def _utc_now_iso() -> str:
    """返回当前 UTC 时间的 ISO 格式字符串"""
    return now_utc().isoformat()
