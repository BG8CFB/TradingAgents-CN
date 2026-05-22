from dataclasses import dataclass
from typing import Optional

from app.data.schema.base.common_fields import CommonFields


@dataclass
class StockBasicInfoSchema(CommonFields):
    """股票基本信息 — 三市场公共字段。"""

    name: Optional[str] = None
    full_symbol: Optional[str] = None  # 带后缀，如 000001.SZ / 00700.HK / AAPL.NASDAQ
    exchange: Optional[str] = None
    industry: Optional[str] = None
    list_status: Optional[str] = None  # L/D/P/S
    list_date: Optional[str] = None
    delist_date: Optional[str] = None
    currency: Optional[str] = None
