"""
stock_adj_factors / stock_adj_factors_hk / stock_adj_factors_us 集合的标准化 Schema

主键: (symbol, trade_date)
语义类型: 时序数据 — 前/后复权因子
"""

from dataclasses import dataclass
from typing import Any, Dict, Optional

from .base import BaseSchema, _utc_now_iso


@dataclass
class AdjFactorsSchema(BaseSchema):
    """复权因子标准 Schema"""

    symbol: str = ""
    trade_date: str = ""          # YYYY-MM-DD

    adj_factor: Optional[float] = None       # 复权因子
    fore_adj_factor: Optional[float] = None  # 前复权因子
    back_adj_factor: Optional[float] = None  # 后复权因子

    @classmethod
    def from_raw(cls, raw: Dict[str, Any], source: str) -> "AdjFactorsSchema":
        """从数据源原始数据构造"""
        return cls(
            symbol=raw.get("symbol", ""),
            trade_date=raw.get("trade_date", ""),
            adj_factor=raw.get("adj_factor"),
            fore_adj_factor=raw.get("fore_adj_factor"),
            back_adj_factor=raw.get("back_adj_factor"),
            data_source=source,
            updated_at=raw.get("updated_at", _utc_now_iso()),
        )
