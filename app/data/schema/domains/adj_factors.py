from dataclasses import dataclass
from typing import Optional

from app.data.schema.base.common_fields import CommonFields


@dataclass
class AdjFactorsSchema(CommonFields):
    """复权因子。"""

    trade_date: Optional[str] = None
    adj_factor: Optional[float] = None       # 复权因子
    fore_adj_factor: Optional[float] = None  # 前复权因子
    back_adj_factor: Optional[float] = None  # 后复权因子
