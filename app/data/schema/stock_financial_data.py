"""
stock_financial_data / stock_financial_data_hk / stock_financial_data_us 集合的标准化 Schema

主键: (symbol, report_period, statement_type)
statement_type: "income" / "balance" / "cashflow" / "indicator"

设计：单集合 + extra_data JSON 字段
  - 公共字段（revenue, net_profit, total_assets, total_equity, roe, eps）直接存储
  - 各报表类型特有字段存入 extra_data 字典
"""

from dataclasses import dataclass
from typing import Any, Dict, Optional

from .base import BaseSchema, get_full_symbol


@dataclass
class FinancialDataSchema(BaseSchema):
    """财务数据标准 Schema"""

    symbol: str = ""
    full_symbol: str = ""
    report_period: str = ""        # YYYY-MM-DD
    statement_type: str = "indicator"  # "income" / "balance" / "cashflow" / "indicator"
    report_type: Optional[str] = None  # "1"=合并, "2"=单季, "4"=母公司
    announce_date: Optional[str] = None

    # 跨类型公共字段
    roe: Optional[float] = None
    roa: Optional[float] = None
    gross_margin: Optional[float] = None     # 毛利率(%)
    net_margin: Optional[float] = None       # 净利率(%)
    debt_ratio: Optional[float] = None       # 资产负债率(%)
    current_ratio: Optional[float] = None    # 流动比率
    eps: Optional[float] = None              # 每股收益
    bps: Optional[float] = None              # 每股净资产
    revenue: Optional[float] = None          # 营业收入（元）
    net_profit: Optional[float] = None       # 净利润（元）
    total_assets: Optional[float] = None     # 总资产（元）
    total_equity: Optional[float] = None     # 所有者权益（元）
    operating_cashflow: Optional[float] = None  # 经营活动现金流量净额（元）

    # 类型特有字段
    extra_data: Optional[Dict[str, Any]] = None

    # 向后兼容：保留 raw_data（旧代码可能引用）
    raw_data: Optional[Dict[str, Any]] = None

    created_at: str = ""

    @classmethod
    def from_raw(cls, raw: Dict[str, Any], source: str, market: str = "CN") -> "FinancialDataSchema":
        """从数据源原始数据构造"""
        symbol = raw.get("symbol", "")
        full_symbol = raw.get("full_symbol") or get_full_symbol(symbol, market)
        return cls(
            symbol=symbol,
            full_symbol=full_symbol,
            report_period=raw.get("report_period", ""),
            statement_type=raw.get("statement_type", "indicator"),
            report_type=raw.get("report_type"),
            announce_date=raw.get("announce_date"),
            roe=raw.get("roe"),
            roa=raw.get("roa"),
            gross_margin=raw.get("gross_margin"),
            net_margin=raw.get("net_margin"),
            debt_ratio=raw.get("debt_ratio"),
            current_ratio=raw.get("current_ratio"),
            eps=raw.get("eps"),
            bps=raw.get("bps"),
            revenue=raw.get("revenue"),
            net_profit=raw.get("net_profit"),
            total_assets=raw.get("total_assets"),
            total_equity=raw.get("total_equity"),
            operating_cashflow=raw.get("operating_cashflow"),
            extra_data=raw.get("extra_data"),
            raw_data=raw.get("raw_data"),
            data_source=source,
            created_at=raw.get("created_at", ""),
            updated_at=raw.get("updated_at", ""),
        )
