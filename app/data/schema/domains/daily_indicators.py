from dataclasses import dataclass
from typing import Optional

from app.data.schema.base.common_fields import CommonFields


@dataclass
class DailyIndicatorsSchema(CommonFields):
    """每日指标 — PE/PB/市值等。"""

    trade_date: Optional[str] = None
    pe_ttm: Optional[float] = None
    pb: Optional[float] = None
    ps_ttm: Optional[float] = None
    turnover_rate: Optional[float] = None
    turnover_rate_f: Optional[float] = None  # 自由流通换手率
    total_mv: Optional[float] = None         # 总市值
    circ_mv: Optional[float] = None          # 流通市值
    volume_ratio: Optional[float] = None     # 量比
    dividend_yield: Optional[float] = None   # 股息率 %
    dividend_yield_ttm: Optional[float] = None  # TTM 股息率
    shares_outstanding: Optional[float] = None  # 总股本
    float_shares: Optional[float] = None        # 流通股本
    southbound_holding: Optional[float] = None       # 南向持股 (HK)
    southbound_holding_ratio: Optional[float] = None  # 南向持股占比 (HK)
