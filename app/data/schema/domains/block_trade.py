from dataclasses import dataclass
from typing import Optional

from app.data.schema.base.common_fields import CommonFields


@dataclass
class BlockTradeSchema(CommonFields):
    """大宗交易 — 大宗交易成交明细。"""

    trade_date: Optional[str] = None
    name: Optional[str] = None           # 股票名称
    price: Optional[float] = None        # 成交价（元）
    volume: Optional[float] = None       # 成交量（股）
    amount: Optional[float] = None       # 成交额（元）
    buyer: Optional[str] = None          # 买方营业部
    seller: Optional[str] = None         # 卖方营业部
