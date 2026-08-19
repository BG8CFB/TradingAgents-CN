"""Tushare HK Adapter — 原始数据 → 标准 Schema。

5 位代码补零，HKD 货币，恒生行业映射。

与 US 逐字相同/可参数化的标准化逻辑（交易日历 / 复权因子 / 日线行情 /
每日指标 / 财务数据）收敛在 app/data/sources/tushare_common/adapters.py；
本类只注入市场差异（symbol 解析、单位倍率 ×1000/×10000、字段候选链）
和 HK 独有的 basic_info / market_quotes 映射。
"""

import logging
from typing import Any, List

import pandas as pd

from app.data.sources.base.adapter import BaseAdapter
from app.data.schema.base.types import _safe_float, _parse_date
from app.data.schema.domains.basic_info import StockBasicInfoSchema
from app.data.schema.domains.market_quotes import MarketQuotesSchema
from app.data.sources.tushare_common.adapters import (
    adapt_adj_factors,
    adapt_daily_indicators,
    adapt_daily_quotes,
    adapt_financial_data,
    adapt_trade_calendar,
)

logger = logging.getLogger(__name__)


def _parse_symbol_from_ts_code(ts_code: str) -> str:
    if isinstance(ts_code, str) and "." in ts_code:
        return ts_code.split(".")[0].zfill(5)
    return str(ts_code).zfill(5)


# HK 财务字段候选链（金额单位千元 → 元 ×1000）
_HK_FINANCIAL_FIELDS = {
    "revenue": ("total_revenue", "revenue"),
    "net_profit": ("net_profit", "n_income"),
    "total_assets": ("total_assets",),
    "total_equity": ("total_hldr_eqy_exc_min_int", "total_equity"),
    "roe": ("roe",),
    "eps": ("eps",),
    "bps": ("bps",),
    "operating_cashflow": ("n_cashflow_act",),
}
_HK_FINANCIAL_SCALES = {
    "revenue": 1000,
    "net_profit": 1000,
    "total_assets": 1000,
    "total_equity": 1000,
    "operating_cashflow": 1000,
}

# HK 每日指标字段（市值单位万元 → 元 ×10000；pe 列映射到 pe_ttm）
_HK_INDICATOR_FIELDS = {
    "pe_ttm": ("pe",),
    "pb": ("pb",),
    "turnover_rate": ("turnover_rate",),
    "total_mv": ("total_mv",),
    "circ_mv": ("circ_mv",),
}
_HK_INDICATOR_SCALES = {"total_mv": 10000, "circ_mv": 10000}


class TushareHKAdapter(BaseAdapter):
    """Tushare 港股数据标准化适配器。"""

    def __init__(self, provider=None):
        super().__init__(provider=provider, market="HK", source_name="tushare_hk")

    def adapt_basic_info(self, raw: Any) -> List[StockBasicInfoSchema]:
        df = raw if isinstance(raw, pd.DataFrame) else pd.DataFrame(raw)
        if df.empty:
            return []
        results = []
        for _, row in df.iterrows():
            get = row.get
            ts_code = str(get("ts_code", ""))
            symbol = _parse_symbol_from_ts_code(ts_code)
            results.append(StockBasicInfoSchema(
                symbol=symbol,
                market="HK",
                data_source="tushare_hk",
                name=get("name", ""),
                full_symbol=f"{symbol}.HK",
                exchange="HKEX",
                industry=get("industry") or get("hangsheng_industry", ""),
                list_status=get("list_status", "L"),
                list_date=_parse_date(get("list_date")),
                delist_date=_parse_date(get("delist_date")),
                currency="HKD",
            ))
        return results

    def adapt_trade_calendar(self, raw: Any) -> List:
        return adapt_trade_calendar(
            raw, market="HK", source_name="tushare_hk", default_exchange="HKEX"
        )

    def adapt_daily_quotes(self, raw: Any) -> List:
        # Tushare HK amount 单位为千港元 → 元（×1000）
        return adapt_daily_quotes(
            raw,
            market="HK",
            source_name="tushare_hk",
            parse_symbol=_parse_symbol_from_ts_code,
            amount_scale=1000,
            compute_change=True,
            with_turnover=True,
        )

    def adapt_daily_indicators(self, raw: Any) -> List:
        # Tushare HK 市值单位为万元 → 元（×10000）
        return adapt_daily_indicators(
            raw,
            market="HK",
            source_name="tushare_hk",
            parse_symbol=_parse_symbol_from_ts_code,
            field_map=_HK_INDICATOR_FIELDS,
            unit_scales=_HK_INDICATOR_SCALES,
        )

    def adapt_adj_factors(self, raw: Any) -> List:
        return adapt_adj_factors(
            raw,
            market="HK",
            source_name="tushare_hk",
            parse_symbol=_parse_symbol_from_ts_code,
        )

    def adapt_financial_data(self, raw: Any) -> List:
        # Tushare HK 财务金额单位为千元 → 元（×1000）
        return adapt_financial_data(
            raw,
            market="HK",
            source_name="tushare_hk",
            parse_symbol=_parse_symbol_from_ts_code,
            field_map=_HK_FINANCIAL_FIELDS,
            unit_scales=_HK_FINANCIAL_SCALES,
        )

    def adapt_market_quotes(self, raw: Any) -> List[MarketQuotesSchema]:
        df = raw if isinstance(raw, pd.DataFrame) else pd.DataFrame(raw)
        if df.empty:
            return []
        results = []
        for _, row in df.iterrows():
            get = row.get
            symbol = _parse_symbol_from_ts_code(str(get("ts_code", get("symbol", ""))))
            results.append(MarketQuotesSchema(
                symbol=symbol,
                market="HK",
                data_source="tushare_hk",
                last_price=_safe_float(get("price") or get("close")),
                last_volume=_safe_float(get("volume") or get("vol")),
            ))
        return results
