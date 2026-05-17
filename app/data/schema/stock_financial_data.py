"""
stock_financial_data / stock_financial_data_hk / stock_financial_data_us 集合的标准化 Schema

主键: (symbol, report_period, data_source)
"""

from dataclasses import dataclass
from typing import Any, Dict, Optional

from .base import BaseSchema, get_full_symbol


@dataclass
class FinancialDataSchema(BaseSchema):
    """财务数据标准 Schema"""

    symbol: str = ""
    full_symbol: str = ""
    report_period: str = ""    # YYYY-MM-DD
    report_type: Optional[str] = None  # "Q1"/"Q2"/"Q3"/"annual"

    roe: Optional[float] = None
    roa: Optional[float] = None
    gross_margin: Optional[float] = None     # 毛利率(%)
    net_margin: Optional[float] = None       # 净利率(%)
    debt_ratio: Optional[float] = None       # 资产负债率(%)
    current_ratio: Optional[float] = None    # 流动比率
    eps: Optional[float] = None              # 每股收益
    bps: Optional[float] = None              # 每股净资产
    revenue: Optional[float] = None          # 营业收入（万元）
    net_profit: Optional[float] = None       # 净利润（万元）
    total_assets: Optional[float] = None     # 总资产（万元）
    total_equity: Optional[float] = None     # 所有者权益（万元）

    raw_data: Optional[Dict[str, Any]] = None  # 原始数据（保留数据源特有字段）

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
            report_type=raw.get("report_type"),
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
            raw_data=raw.get("raw_data"),
            data_source=source,
            created_at=raw.get("created_at", ""),
            updated_at=raw.get("updated_at", ""),
        )
