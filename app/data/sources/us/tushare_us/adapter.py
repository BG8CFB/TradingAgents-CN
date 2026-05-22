"""Tushare US Adapter — 原始数据 → 标准 Schema。

ts_code .O/.N 映射，USD 货币。
"""

import logging
from typing import Any, List

import pandas as pd

from app.data.sources.base.adapter import BaseAdapter
from app.data.schema.base.types import _safe_float, _parse_date
from app.data.schema.domains.basic_info import StockBasicInfoSchema
from app.data.schema.domains.trade_calendar import TradeCalendarSchema
from app.data.schema.domains.daily_quotes import DailyQuotesSchema
from app.data.schema.domains.adj_factors import AdjFactorsSchema
from app.data.schema.domains.financial_data import FinancialDataSchema

logger = logging.getLogger(__name__)


def _parse_symbol_from_ts_code(ts_code: str) -> str:
    if isinstance(ts_code, str) and "." in ts_code:
        return ts_code.split(".")[0].upper()
    return str(ts_code).upper()


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

    def adapt_trade_calendar(self, raw: Any) -> List[TradeCalendarSchema]:
        df = raw if isinstance(raw, pd.DataFrame) else pd.DataFrame(raw)
        if df.empty:
            return []
        results = []
        for _, row in df.iterrows():
            get = row.get
            cal_date = _parse_date(get("cal_date"))
            if not cal_date:
                continue
            results.append(TradeCalendarSchema(
                symbol="__calendar__",
                market="US",
                data_source="tushare_us",
                exchange=get("exchange", "NYSE"),
                cal_date=cal_date,
                is_open=bool(get("is_open", 1)),
                pretrade_date=_parse_date(get("pretrade_date")),
            ))
        return results

    def adapt_daily_quotes(self, raw: Any) -> List[DailyQuotesSchema]:
        df = raw if isinstance(raw, pd.DataFrame) else pd.DataFrame(raw)
        if df.empty:
            return []
        results = []
        for _, row in df.iterrows():
            get = row.get
            symbol = _parse_symbol_from_ts_code(str(get("ts_code", "")))
            trade_date = _parse_date(get("trade_date"))
            if not trade_date:
                continue

            close = _safe_float(get("close"))
            pre_close = _safe_float(get("pre_close"))
            change = _safe_float(get("change"))
            pct_chg = _safe_float(get("pct_chg"))

            results.append(DailyQuotesSchema(
                symbol=symbol,
                market="US",
                data_source="tushare_us",
                trade_date=trade_date,
                period="daily",
                open=_safe_float(get("open")),
                high=_safe_float(get("high")),
                low=_safe_float(get("low")),
                close=close,
                pre_close=pre_close,
                change=change,
                pct_chg=pct_chg,
                volume=_safe_float(get("vol")),
                amount=_safe_float(get("amount")),
            ))
        return results

    def adapt_adj_factors(self, raw: Any) -> List[AdjFactorsSchema]:
        df = raw if isinstance(raw, pd.DataFrame) else pd.DataFrame(raw)
        if df.empty:
            return []
        results = []
        for _, row in df.iterrows():
            get = row.get
            symbol = _parse_symbol_from_ts_code(str(get("ts_code", "")))
            trade_date = _parse_date(get("trade_date"))
            if not trade_date:
                continue
            results.append(AdjFactorsSchema(
                symbol=symbol,
                market="US",
                data_source="tushare_us",
                trade_date=trade_date,
                adj_factor=_safe_float(get("adj_factor")),
            ))
        return results

    def adapt_financial_data(self, raw: Any) -> List[FinancialDataSchema]:
        df = raw if isinstance(raw, pd.DataFrame) else pd.DataFrame(raw)
        if df.empty:
            return []
        results = []
        for _, row in df.iterrows():
            get = row.get
            symbol = _parse_symbol_from_ts_code(str(get("ts_code", "")))
            results.append(FinancialDataSchema(
                symbol=symbol,
                market="US",
                data_source="tushare_us",
                report_period=_parse_date(get("end_date") or get("ann_date")),
                announce_date=_parse_date(get("ann_date")),
                revenue=_safe_float(get("revenue") or get("total_revenue")),
                net_profit=_safe_float(get("net_income")),
                total_assets=_safe_float(get("total_assets")),
                total_equity=_safe_float(get("total_equity")),
                roe=_safe_float(get("roe")),
                eps=_safe_float(get("eps")),
                operating_cashflow=_safe_float(get("operating_cashflow")),
            ))
        return results
