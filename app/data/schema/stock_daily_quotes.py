"""
stock_daily_quotes / stock_daily_quotes_hk / stock_daily_quotes_us 集合的标准化 Schema

主键: (symbol, trade_date, data_source, period)
单位统一: volume=股, amount=元
"""

from dataclasses import dataclass
from typing import Any, Dict, Optional

from .base import BaseSchema, get_full_symbol


@dataclass
class StockDailyQuoteSchema(BaseSchema):
    """历史行情标准 Schema"""

    symbol: str = ""
    full_symbol: str = ""
    trade_date: str = ""       # YYYY-MM-DD
    period: str = "daily"      # "daily" / "weekly" / "monthly"

    open: Optional[float] = None
    high: Optional[float] = None
    low: Optional[float] = None
    close: Optional[float] = None
    pre_close: Optional[float] = None
    volume: Optional[float] = None   # 统一为股
    amount: Optional[float] = None   # 统一为元
    change: Optional[float] = None
    pct_chg: Optional[float] = None
    turnover_rate: Optional[float] = None

    created_at: str = ""

    def __post_init__(self):
        if not self.full_symbol and self.symbol:
            # 从 symbol 推断市场（简化版，Adapter 应直接提供）
            pass

    @classmethod
    def from_raw(cls, raw: Dict[str, Any], source: str, market: str = "CN") -> "StockDailyQuoteSchema":
        """从数据源原始数据构造"""
        symbol = raw.get("symbol", "")
        full_symbol = raw.get("full_symbol") or get_full_symbol(symbol, market)
        return cls(
            symbol=symbol,
            full_symbol=full_symbol,
            trade_date=raw.get("trade_date", ""),
            period=raw.get("period", "daily"),
            open=raw.get("open"),
            high=raw.get("high"),
            low=raw.get("low"),
            close=raw.get("close"),
            pre_close=raw.get("pre_close"),
            volume=raw.get("volume"),
            amount=raw.get("amount"),
            change=raw.get("change"),
            pct_chg=raw.get("pct_chg"),
            turnover_rate=raw.get("turnover_rate"),
            data_source=source,
            created_at=raw.get("created_at", ""),
            updated_at=raw.get("updated_at", ""),
        )
