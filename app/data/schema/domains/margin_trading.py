from dataclasses import dataclass
from typing import Optional

from app.data.schema.base.common_fields import CommonFields


@dataclass
class MarginTradingSchema(CommonFields):
    """融资融券 — 个股两融余额与交易明细。"""

    trade_date: Optional[str] = None
    margin_balance: Optional[float] = None      # 融资余额（元）
    short_balance: Optional[float] = None       # 融券余额（元）
    margin_buy_amount: Optional[float] = None   # 融资买入额（元）
    short_sell_volume: Optional[float] = None   # 融券卖出量（股）
    total_balance: Optional[float] = None       # 融资融券余额（元）
    short_volume: Optional[float] = None        # 融券余量（股）
