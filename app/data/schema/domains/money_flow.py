from dataclasses import dataclass
from typing import Optional

from app.data.schema.base.common_fields import CommonFields


@dataclass
class MoneyFlowSchema(CommonFields):
    """资金流向 — 个股主力/散户资金净流入。"""

    trade_date: Optional[str] = None
    main_net_inflow: Optional[float] = None        # 主力净流入（元）
    main_net_inflow_pct: Optional[float] = None     # 主力净流入占比 %（仅 AKShare 提供，Tushare 无此字段为 None）
    huge_net_inflow: Optional[float] = None         # 超大单净流入（元）
    large_net_inflow: Optional[float] = None        # 大单净流入（元）
    medium_net_inflow: Optional[float] = None       # 中单净流入（元）
    small_net_inflow: Optional[float] = None        # 小单净流入（元）
