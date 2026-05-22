from dataclasses import dataclass
from typing import Optional

from app.data.schema.base.common_fields import CommonFields


@dataclass
class DailyQuotesSchema(CommonFields):
    """日线行情 — OHLCV + 涨跌。"""

    trade_date: Optional[str] = None
    period: Optional[str] = None        # daily / weekly / monthly
    open: Optional[float] = None
    high: Optional[float] = None
    low: Optional[float] = None
    close: Optional[float] = None
    pre_close: Optional[float] = None
    change: Optional[float] = None      # 涨跌额
    pct_chg: Optional[float] = None     # 涨跌幅 %
    volume: Optional[float] = None      # 成交量（股）
    amount: Optional[float] = None      # 成交额（元）
    turnover_rate: Optional[float] = None  # 换手率 %
