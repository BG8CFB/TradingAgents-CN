"""
stock_basic_info / stock_basic_info_hk / stock_basic_info_us 集合的标准化 Schema

主键: (symbol, data_source)
"""

from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from .base import BaseSchema, MarketType, get_full_symbol


@dataclass
class StockBasicInfoSchema(BaseSchema):
    """股票基础信息标准 Schema"""

    symbol: str = ""
    full_symbol: str = ""
    name: str = ""
    market: str = ""          # "CN" / "HK" / "US"
    exchange: str = ""         # "SSE"/"SZSE"/"BSE"/"HKG"/"NYSE"/"NASDAQ"
    industry: Optional[str] = None
    area: Optional[str] = None
    list_date: Optional[str] = None  # YYYY-MM-DD
    currency: Optional[str] = None   # "CNY"/"HKD"/"USD"

    # 市值（统一为亿元）
    total_mv: Optional[float] = None
    circ_mv: Optional[float] = None

    # 估值指标
    pe: Optional[float] = None
    pe_ttm: Optional[float] = None
    pb: Optional[float] = None
    pb_mrq: Optional[float] = None
    ps: Optional[float] = None
    ps_ttm: Optional[float] = None

    # 盈利能力
    roe: Optional[float] = None

    # 交易指标
    turnover_rate: Optional[float] = None
    volume_ratio: Optional[float] = None

    # 扩展信息（HK/US 使用）
    name_en: Optional[str] = None
    sector: Optional[str] = None
    board: Optional[str] = None
    industry_code: Optional[str] = None
    delist_date: Optional[str] = None
    status: Optional[str] = None    # "L"=上市 / "D"=退市 / "P"=暂停
    is_hs: Optional[bool] = None    # 是否沪深港通标的

    # 股本信息
    total_shares: Optional[float] = None
    float_shares: Optional[float] = None
    shares_outstanding: Optional[float] = None

    # 其他（HK/US 使用）
    employees: Optional[float] = None
    website: Optional[str] = None
    description: Optional[str] = None

    def __post_init__(self):
        # 自动生成 full_symbol（如果未提供）
        if not self.full_symbol and self.symbol and self.market:
            self.full_symbol = get_full_symbol(self.symbol, self.market)

    @classmethod
    def from_raw(cls, raw: Dict[str, Any], source: str, market: str = "CN") -> "StockBasicInfoSchema":
        """
        从数据源原始数据构造（由各 Adapter 调用）。
        Adapter 负责：字段映射、单位转换、数据过滤。
        此方法只做最终的 Schema 构造。
        """
        return cls(
            symbol=raw.get("symbol", ""),
            full_symbol=raw.get("full_symbol", ""),
            name=raw.get("name", ""),
            market=market,
            exchange=raw.get("exchange", ""),
            industry=raw.get("industry"),
            area=raw.get("area"),
            list_date=raw.get("list_date"),
            currency=raw.get("currency"),
            total_mv=raw.get("total_mv"),
            circ_mv=raw.get("circ_mv"),
            pe=raw.get("pe"),
            pe_ttm=raw.get("pe_ttm"),
            pb=raw.get("pb"),
            pb_mrq=raw.get("pb_mrq"),
            ps=raw.get("ps"),
            ps_ttm=raw.get("ps_ttm"),
            roe=raw.get("roe"),
            turnover_rate=raw.get("turnover_rate"),
            volume_ratio=raw.get("volume_ratio"),
            name_en=raw.get("name_en"),
            sector=raw.get("sector"),
            board=raw.get("board"),
            industry_code=raw.get("industry_code"),
            delist_date=raw.get("delist_date"),
            status=raw.get("status"),
            is_hs=raw.get("is_hs"),
            total_shares=raw.get("total_shares"),
            float_shares=raw.get("float_shares"),
            shares_outstanding=raw.get("shares_outstanding"),
            employees=raw.get("employees"),
            website=raw.get("website"),
            description=raw.get("description"),
            data_source=source,
            updated_at=raw.get("updated_at", ""),
        )
