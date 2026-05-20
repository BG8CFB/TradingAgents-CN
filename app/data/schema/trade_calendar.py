"""
trade_calendar / trade_calendar_hk / trade_calendar_us 集合的标准化 Schema

主键: (exchange, cal_date)
语义类型: 实体数据 — 各交易所交易日历
"""

from dataclasses import dataclass
from typing import Any, Dict, Optional

from .base import BaseSchema, _utc_now_iso


@dataclass
class TradeCalendarSchema(BaseSchema):
    """交易日历标准 Schema"""

    exchange: str = ""             # 交易所: SSE / SZSE / BSE / HKEX / NYSE / NASDAQ
    cal_date: str = ""             # YYYY-MM-DD
    is_open: bool = False          # 是否交易日
    pretrade_date: Optional[str] = None  # 上一个交易日 YYYY-MM-DD

    @classmethod
    def from_raw(cls, raw: Dict[str, Any], source: str) -> "TradeCalendarSchema":
        """从数据源原始数据构造"""
        return cls(
            exchange=raw.get("exchange", ""),
            cal_date=raw.get("cal_date", ""),
            is_open=bool(raw.get("is_open", False)),
            pretrade_date=raw.get("pretrade_date"),
            data_source=source,
            updated_at=raw.get("updated_at", _utc_now_iso()),
        )
