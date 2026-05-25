from dataclasses import dataclass
from typing import Optional

from app.data.schema.base.common_fields import CommonFields


@dataclass
class MarketQuotesSchema(CommonFields):
    """市场实时快照。"""

    # 核心行情
    open: Optional[float] = None
    high: Optional[float] = None
    low: Optional[float] = None
    close: Optional[float] = None         # 最新价（等同于 last_price）
    pre_close: Optional[float] = None     # 昨收价
    pct_chg: Optional[float] = None       # 涨跌幅 %
    volume: Optional[float] = None        # 成交量（股）
    amount: Optional[float] = None        # 成交额（元）
    turnover_rate: Optional[float] = None  # 换手率 %

    # 兼容字段（旧代码可能读取）
    last_price: Optional[float] = None
    last_volume: Optional[float] = None
    last_updated: Optional[str] = None    # ISO 8601 UTC

    # 交易日期
    trade_date: Optional[str] = None

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
