"""Tushare US Adapter — 原始数据 → 标准 Schema。

ts_code .O/.N 映射，USD 货币。

与 HK 逐字相同/可参数化的标准化逻辑（交易日历 / 复权因子 / 日线行情 /
财务数据）收敛在 app/data/sources/tushare_common/adapters.py；
本类只注入市场差异（symbol 大写解析、无单位换算、US 字段候选链）
和 US 独有的 basic_info 映射。
"""

import logging
from typing import Any, List

import pandas as pd

from app.data.sources.base.adapter import BaseAdapter
from app.data.schema.base.types import _parse_date
from app.data.schema.domains.basic_info import StockBasicInfoSchema
from app.data.sources.tushare_common.adapters import (
    adapt_adj_factors,
    adapt_daily_quotes,
    adapt_financial_data,
    adapt_trade_calendar,
)

logger = logging.getLogger(__name__)


def _parse_symbol_from_ts_code(ts_code: str) -> str:
    if isinstance(ts_code, str) and "." in ts_code:
        return ts_code.split(".")[0].upper()
    return str(ts_code).upper()


# US 财务字段候选链（原始单位为美元，无换算）
_US_FINANCIAL_FIELDS = {
    "revenue": ("revenue", "total_revenue"),
    "net_profit": ("net_income",),
    "total_assets": ("total_assets",),
    "total_equity": ("total_equity",),
    "roe": ("roe",),
    "eps": ("eps",),
    "operating_cashflow": ("operating_cashflow",),
}
_US_FINANCIAL_SCALES: dict = {}


class TushareUSAdapter(BaseAdapter):
    """Tushare 美股数据标准化适配器。"""

    def __init__(self, provider=None):
        super().__init__(provider=provider, market="US", source_name="tushare_us")

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
                market="US",
                data_source="tushare_us",
                name=get("name", ""),
                full_symbol=symbol,
                exchange=get("exchange", ""),
                industry=get("industry", ""),
                list_date=_parse_date(get("list_date")),
                delist_date=_parse_date(get("delist_date")),
                currency="USD",
            ))
        return results

    def adapt_trade_calendar(self, raw: Any) -> List:
        return adapt_trade_calendar(
            raw, market="US", source_name="tushare_us", default_exchange="NYSE"
        )

    def adapt_daily_quotes(self, raw: Any) -> List:
        return adapt_daily_quotes(
            raw,
            market="US",
            source_name="tushare_us",
            parse_symbol=_parse_symbol_from_ts_code,
            amount_scale=1.0,
            compute_change=False,
            with_turnover=False,
        )

    def adapt_adj_factors(self, raw: Any) -> List:
        return adapt_adj_factors(
            raw,
            market="US",
            source_name="tushare_us",
            parse_symbol=_parse_symbol_from_ts_code,
        )

    def adapt_financial_data(self, raw: Any) -> List:
        return adapt_financial_data(
            raw,
            market="US",
            source_name="tushare_us",
            parse_symbol=_parse_symbol_from_ts_code,
            field_map=_US_FINANCIAL_FIELDS,
            unit_scales=_US_FINANCIAL_SCALES,
        )
