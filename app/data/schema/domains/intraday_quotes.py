from dataclasses import dataclass
from typing import Optional

from app.data.schema.base.common_fields import CommonFields


@dataclass
class IntradayQuotesSchema(CommonFields):
    """分钟线行情 — 盘中分时 OHLCV。"""

    datetime: Optional[str] = None       # 交易时间（YYYY-MM-DD HH:MM:SS）
    freq: Optional[str] = None           # 频率（1/5/15/30/60 min）
    open: Optional[float] = None
    high: Optional[float] = None
    low: Optional[float] = None
    close: Optional[float] = None
    volume: Optional[float] = None       # 成交量（股）
    amount: Optional[float] = None       # 成交额（元）
    pct_chg: Optional[float] = None      # 涨跌幅 %
