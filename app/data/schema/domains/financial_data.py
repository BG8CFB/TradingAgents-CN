from dataclasses import dataclass
from typing import Optional

from app.data.schema.base.common_fields import CommonFields


@dataclass
class FinancialDataSchema(CommonFields):
    """财务数据 — 三表 + 财务指标。"""

    report_period: Optional[str] = None         # 报告期截止日
    statement_type: Optional[str] = None        # income / balance / cashflow / indicator
    report_type: Optional[str] = None           # Q1/Q2/Q3/FY/H1/H2/1/2/4
    fiscal_year: Optional[int] = None
    fiscal_period: Optional[str] = None         # 财年内期次
    announce_date: Optional[str] = None
    filing_url: Optional[str] = None            # SEC EDGAR / 披露易链接

    # 核心财务字段
    revenue: Optional[float] = None             # 营业收入
    revenue_hkd: Optional[float] = None         # 港股折算 HKD
    net_profit: Optional[float] = None          # 净利润
    net_profit_hkd: Optional[float] = None      # 港股折算 HKD
    total_assets: Optional[float] = None        # 总资产
    total_equity: Optional[float] = None        # 净资产
    operating_cashflow: Optional[float] = None  # 经营活动现金流净额
    free_cashflow: Optional[float] = None       # 自由现金流 (US)

    # 财务指标
    roe: Optional[float] = None                 # 净资产收益率 %
    roa: Optional[float] = None                 # 总资产收益率 %
    gross_margin: Optional[float] = None        # 毛利率 %
    net_margin: Optional[float] = None          # 净利率 %
    debt_ratio: Optional[float] = None          # 资产负债率 %
    debt_to_equity: Optional[float] = None      # D/E (US)
    current_ratio: Optional[float] = None       # 流动比率
    eps: Optional[float] = None                 # 每股收益
    eps_basic: Optional[float] = None           # 基本每股收益 (US)
    eps_diluted: Optional[float] = None         # 稀释每股收益 (US)
    bps: Optional[float] = None                 # 每股净资产
    dividend_per_share: Optional[float] = None  # 每股股息 (HK)
