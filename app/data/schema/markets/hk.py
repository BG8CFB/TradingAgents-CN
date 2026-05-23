"""港股市场特化字段。"""

from dataclasses import dataclass
from typing import Optional


@dataclass
class HKBasicInfoFields:
    """港股基本信息特化字段。"""

    name_en: Optional[str] = None
    board: Optional[str] = None                  # MAIN / GEM
    industry_l1: Optional[str] = None            # 恒生一级行业
    industry_l2: Optional[str] = None            # 恒生二级行业
    sector: Optional[str] = None                 # 板块（金融、地产、科技）
    connect_status: Optional[str] = None          # stock_connect_sh / stock_connect_sz / stock_connect_both / none
    dual_listed: Optional[bool] = None
    dual_listed_us_symbol: Optional[str] = None   # 对应美股 ticker
    dual_listed_a_symbol: Optional[str] = None     # 对应 A 股 symbol
    weighted_voting_rights: Optional[bool] = None   # 同股不同权
    chinese_company: Optional[bool] = None          # 中资股


@dataclass
class HKDailyIndicatorsFields:
    """港股每日指标特化字段。"""

    dividend_yield: Optional[float] = None
    dividend_yield_ttm: Optional[float] = None
    southbound_holding: Optional[float] = None          # 南向持股数
    southbound_holding_ratio: Optional[float] = None    # 南向持股占比 %


@dataclass
class HKCorporateActionsFields:
    """港股公司行为特化字段。"""

    amount_hkd: Optional[float] = None  # 折算 HKD 后每股金额


@dataclass
class HKMarketQuotesFields:
    """港股市场快照特化字段。"""

    quote_source_type: Optional[str] = None  # delayed / realtime
    bid_price: Optional[float] = None
    ask_price: Optional[float] = None
    bid_volume: Optional[float] = None
    ask_volume: Optional[float] = None
    session: Optional[str] = None  # morning / lunch_break / afternoon / closed / pre_open / closing_auction


@dataclass
class HKFinancialDataFields:
    """港股财务数据特化字段。"""

    currency: Optional[str] = None           # 报告币种
    revenue_hkd: Optional[float] = None      # 折算 HKD
    net_profit_hkd: Optional[float] = None   # 折算 HKD
    dividend_per_share: Optional[float] = None
