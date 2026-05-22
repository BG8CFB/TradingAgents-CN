from dataclasses import dataclass
from typing import Optional

from app.data.schema.base.common_fields import CommonFields


@dataclass
class TradeCalendarSchema(CommonFields):
    """交易日历。"""

    exchange: Optional[str] = None      # SSE/SZSE/BSE/HKEX/NYSE/NASDAQ
    cal_date: Optional[str] = None      # YYYY-MM-DD
    is_open: Optional[bool] = None      # 是否交易日
    pretrade_date: Optional[str] = None  # 上一个交易日
