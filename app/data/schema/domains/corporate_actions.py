from dataclasses import dataclass
from typing import Optional

from app.data.schema.base.common_fields import CommonFields


@dataclass
class CorporateActionsSchema(CommonFields):
    """公司行为 — 分红/拆股/红股/供股。"""

    ex_date: Optional[str] = None           # 除权除息日
    record_date: Optional[str] = None       # 登记日
    pay_date: Optional[str] = None          # 派发日
    action_type: Optional[str] = None       # cash_dividend / stock_split / bonus_issue 等
    amount: Optional[float] = None          # 现金分红金额（每股，原币种）
    currency: Optional[str] = None          # 分红币种
    amount_hkd: Optional[float] = None      # 折算 HKD（港股）
    ratio_from: Optional[float] = None      # 拆股/红股/供股前基数
    ratio_to: Optional[float] = None        # 拆股/红股/供股后对应数
    rights_price: Optional[float] = None    # 供股价（rights_issue）
    announce_date: Optional[str] = None     # 公告日期
