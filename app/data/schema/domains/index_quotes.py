from dataclasses import dataclass
from typing import Optional

from app.data.schema.base.common_fields import CommonFields


@dataclass
class IndexQuotesSchema(CommonFields):
    """指数日线 — OHLCV + 涨跌（symbol 为指数规范码，如 000300.SH / HSI / SPX）。"""

    trade_date: Optional[str] = None
    open: Optional[float] = None
    high: Optional[float] = None
    low: Optional[float] = None
    close: Optional[float] = None
    pre_close: Optional[float] = None
    change: Optional[float] = None      # 涨跌额
    pct_chg: Optional[float] = None     # 涨跌幅 %
    volume: Optional[float] = None      # 成交量（股）
    amount: Optional[float] = None      # 成交额（元）
