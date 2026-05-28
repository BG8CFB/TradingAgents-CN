from dataclasses import dataclass
from typing import Optional

from app.data.schema.base.common_fields import CommonFields


@dataclass
class DragonTigerSchema(CommonFields):
    """龙虎榜 — 异常波动个股上榜明细。"""

    trade_date: Optional[str] = None
    name: Optional[str] = None           # 股票名称
    close: Optional[float] = None        # 收盘价
    pct_chg: Optional[float] = None      # 涨跌幅 %
    direction: Optional[str] = None      # 上榜理由（Tushare）/ 营业部方向（AKShare）
    buy_amount: Optional[float] = None   # 买入金额（元）
    sell_amount: Optional[float] = None  # 卖出金额（元）
    net_amount: Optional[float] = None   # 净金额（元）
