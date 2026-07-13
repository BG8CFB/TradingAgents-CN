from dataclasses import dataclass
from typing import Optional

from app.data.schema.base.common_fields import CommonFields


@dataclass
class MoneyFlowSchema(CommonFields):
    """资金流向 — 个股主力/散户资金净流入。"""

    trade_date: Optional[str] = None
    main_net_inflow: Optional[float] = None        # 主力净流入（元）
    main_net_inflow_pct: Optional[float] = None     # 净流入占比（AKShare）/ 净流入量手（Tushare）
    huge_net_inflow: Optional[float] = None         # 超大单净流入（元，Tushare为(买入-卖出)×10000）
    large_net_inflow: Optional[float] = None        # 大单净流入（元，Tushare为(买入-卖出)×10000）
    medium_net_inflow: Optional[float] = None       # 中单净流入（元，Tushare为(买入-卖出)×10000）
    small_net_inflow: Optional[float] = None        # 小单净流入（元，Tushare为(买入-卖出)×10000）
