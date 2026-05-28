from dataclasses import dataclass
from typing import Optional

from app.data.schema.base.common_fields import CommonFields


@dataclass
class MarginTradingSchema(CommonFields):
    """融资融券 — 个股两融余额与交易明细。"""

    trade_date: Optional[str] = None
    rzye: Optional[float] = None         # 融资余额（元）
    rqye: Optional[float] = None         # 融券余额（元）
    rz_buy: Optional[float] = None       # 融资买入额（元）
    rq_sell: Optional[float] = None      # 融券卖出额（元）
    rzrqye: Optional[float] = None       # 融资融券余额（元）
    rqyl: Optional[float] = None         # 融券余量（股）
