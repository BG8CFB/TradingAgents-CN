from dataclasses import dataclass
from typing import Optional

from app.data.schema.base.common_fields import CommonFields


@dataclass
class MarketQuotesSchema(CommonFields):
    """市场实时快照。"""

    last_price: Optional[float] = None
    last_volume: Optional[float] = None
    last_updated: Optional[str] = None  # ISO 8601 UTC

    # 港股准实时增强
    quote_source_type: Optional[str] = None  # delayed / realtime
    bid_price: Optional[float] = None
    ask_price: Optional[float] = None
    bid_volume: Optional[float] = None
    ask_volume: Optional[float] = None

    # 美股盘前盘后
    pre_market_price: Optional[float] = None
    pre_market_change: Optional[float] = None
    pre_market_volume: Optional[float] = None
    post_market_price: Optional[float] = None
    post_market_change: Optional[float] = None
    post_market_volume: Optional[float] = None

    # 通用
    session: Optional[str] = None  # market session 枚举值
