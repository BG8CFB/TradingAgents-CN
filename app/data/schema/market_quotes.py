"""
market_quotes / market_quotes_hk / market_quotes_us 集合的标准化 Schema

数据契约：每只股票仅保留一条最新快照，主键 symbol（唯一索引）。
data_source 记录最后一次写入来源，不参与多源对比。
"""

from dataclasses import dataclass
from typing import Any, Dict, Optional

from .base import BaseSchema


@dataclass
class MarketQuoteSchema(BaseSchema):
    """实时行情快照标准 Schema"""

    symbol: str = ""           # 主键
    trade_date: Optional[str] = None  # YYYY-MM-DD
    open: Optional[float] = None
    high: Optional[float] = None
    low: Optional[float] = None
    close: Optional[float] = None
    pre_close: Optional[float] = None
    pct_chg: Optional[float] = None
    volume: Optional[float] = None    # 股
    amount: Optional[float] = None    # 元

    @classmethod
    def from_raw(cls, raw: Dict[str, Any], source: str) -> "MarketQuoteSchema":
        """从数据源原始数据构造"""
        return cls(
            symbol=raw.get("symbol", ""),
            trade_date=raw.get("trade_date"),
            open=raw.get("open"),
            high=raw.get("high"),
            low=raw.get("low"),
            close=raw.get("close"),
            pre_close=raw.get("pre_close"),
            pct_chg=raw.get("pct_chg"),
            volume=raw.get("volume"),
            amount=raw.get("amount"),
            data_source=source,
            updated_at=raw.get("updated_at", ""),
        )
