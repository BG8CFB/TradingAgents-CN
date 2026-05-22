"""美股市场特化字段。"""

from dataclasses import dataclass
from typing import Optional


@dataclass
class USBasicInfoFields:
    """美股基本信息特化字段。"""

    sector: Optional[str] = None             # GICS 一级行业
    country: Optional[str] = None            # 注册地国家
    market_cap_tier: Optional[str] = None    # mega / large / mid / small / micro / nano
    isin: Optional[str] = None
    cik: Optional[str] = None                # SEC CIK 编号
    is_adr: Optional[bool] = None
    home_country: Optional[str] = None       # ADR 母国家


@dataclass
class USDailyQuotesFields:
    """美货行情特化字段。"""

    adj_close: Optional[float] = None  # 调整后收盘价


@dataclass
class USFinancialDataFields:
    """美股财务数据特化字段。"""

    eps_basic: Optional[float] = None
    eps_diluted: Optional[float] = None
    free_cashflow: Optional[float] = None
    debt_to_equity: Optional[float] = None
    ev_ebitda: Optional[float] = None


@dataclass
class USMarketQuotesFields:
    """美股市场快照特化字段。"""

    pre_market_price: Optional[float] = None
    pre_market_change: Optional[float] = None
    pre_market_volume: Optional[float] = None
    post_market_price: Optional[float] = None
    post_market_change: Optional[float] = None
    post_market_volume: Optional[float] = None
    session: Optional[str] = None  # pre / regular / post / closed
