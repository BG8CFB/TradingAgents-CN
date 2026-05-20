"""
stock_daily_indicators / stock_daily_indicators_hk / stock_daily_indicators_us 集合的标准化 Schema

主键: (symbol, trade_date)
语义类型: 时序数据 — PE/PB/市值/换手率等每日指标
"""

from dataclasses import dataclass
from typing import Any, Dict, Optional

from .base import BaseSchema, _utc_now_iso


@dataclass
class DailyIndicatorsSchema(BaseSchema):
    """每日指标标准 Schema"""

    symbol: str = ""
    trade_date: str = ""          # YYYY-MM-DD

    pe_ttm: Optional[float] = None         # 市盈率（TTM）
    pb: Optional[float] = None             # 市净率
    ps_ttm: Optional[float] = None         # 市销率（TTM）
    turnover_rate: Optional[float] = None  # 换手率（%）
    turnover_rate_f: Optional[float] = None  # 自由流通换手率（%）
    total_mv: Optional[float] = None       # 总市值（元）
    circ_mv: Optional[float] = None        # 流通市值（元）
    volume_ratio: Optional[float] = None   # 量比

    @classmethod
    def from_raw(cls, raw: Dict[str, Any], source: str) -> "DailyIndicatorsSchema":
        """从数据源原始数据构造"""
        return cls(
            symbol=raw.get("symbol", ""),
            trade_date=raw.get("trade_date", ""),
            pe_ttm=raw.get("pe_ttm"),
            pb=raw.get("pb"),
            ps_ttm=raw.get("ps_ttm"),
            turnover_rate=raw.get("turnover_rate"),
            turnover_rate_f=raw.get("turnover_rate_f"),
            total_mv=raw.get("total_mv"),
            circ_mv=raw.get("circ_mv"),
            volume_ratio=raw.get("volume_ratio"),
            data_source=source,
            updated_at=raw.get("updated_at", _utc_now_iso()),
        )
