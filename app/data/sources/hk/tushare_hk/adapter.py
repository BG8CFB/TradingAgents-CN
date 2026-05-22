"""Tushare HK Adapter — 原始数据 → 标准 Schema。

5 位代码补零，HKD 货币，恒生行业映射。
"""

import logging
from typing import Any, List

import pandas as pd

from app.data.sources.base.adapter import BaseAdapter
from app.data.schema.base.types import _safe_float, _parse_date
from app.data.schema.domains.basic_info import StockBasicInfoSchema
from app.data.schema.domains.trade_calendar import TradeCalendarSchema
from app.data.schema.domains.daily_quotes import DailyQuotesSchema
from app.data.schema.domains.daily_indicators import DailyIndicatorsSchema
from app.data.schema.domains.adj_factors import AdjFactorsSchema
from app.data.schema.domains.financial_data import FinancialDataSchema
from app.data.schema.domains.market_quotes import MarketQuotesSchema

logger = logging.getLogger(__name__)


def _parse_symbol_from_ts_code(ts_code: str) -> str:
    if isinstance(ts_code, str) and "." in ts_code:
        return ts_code.split(".")[0].zfill(5)
    return str(ts_code).zfill(5)


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
                market="HK",
                data_source="tushare_hk",
                exchange=get("exchange", "HKEX"),
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
            if change is None and close is not None and pre_close is not None:
                change = round(close - pre_close, 4)
            if pct_chg is None and close is not None and pre_close is not None and pre_close != 0:
                pct_chg = round((close - pre_close) / pre_close * 100, 4)

            # Tushare HK amount 单位为千港元 → 元
            amount = _safe_float(get("amount"))
            if amount is not None:
                amount = amount * 1000

            results.append(DailyQuotesSchema(
                symbol=symbol,
                market="HK",
                data_source="tushare_hk",
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
                amount=amount,
                turnover_rate=_safe_float(get("turnover_rate")),
            ))
        return results

    def adapt_daily_indicators(self, raw: Any) -> List[DailyIndicatorsSchema]:
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
            # Tushare HK 市值单位为万元 → 元
            total_mv = _safe_float(get("total_mv"))
            if total_mv is not None:
                total_mv = total_mv * 10000
            circ_mv = _safe_float(get("circ_mv"))
            if circ_mv is not None:
                circ_mv = circ_mv * 10000

            results.append(DailyIndicatorsSchema(
                symbol=symbol,
                market="HK",
                data_source="tushare_hk",
                trade_date=trade_date,
                pe_ttm=_safe_float(get("pe")),
                pb=_safe_float(get("pb")),
                turnover_rate=_safe_float(get("turnover_rate")),
                total_mv=total_mv,
                circ_mv=circ_mv,
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
                market="HK",
                data_source="tushare_hk",
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
            # Tushare HK 财务金额单位为千元 → 元
            revenue = _safe_float(get("total_revenue") or get("revenue"))
            if revenue is not None:
                revenue = revenue * 1000
            net_profit = _safe_float(get("net_profit") or get("n_income"))
            if net_profit is not None:
                net_profit = net_profit * 1000
            total_assets = _safe_float(get("total_assets"))
            if total_assets is not None:
                total_assets = total_assets * 1000
            total_equity = _safe_float(
                get("total_hldr_eqy_exc_min_int") or get("total_equity")
            )
            if total_equity is not None:
                total_equity = total_equity * 1000
            operating_cashflow = _safe_float(get("n_cashflow_act"))
            if operating_cashflow is not None:
                operating_cashflow = operating_cashflow * 1000

            results.append(FinancialDataSchema(
                symbol=symbol,
                market="HK",
                data_source="tushare_hk",
                report_period=_parse_date(get("end_date") or get("ann_date")),
                announce_date=_parse_date(get("ann_date")),
                revenue=revenue,
                net_profit=net_profit,
                total_assets=total_assets,
                total_equity=total_equity,
                roe=_safe_float(get("roe")),
                eps=_safe_float(get("eps")),
                bps=_safe_float(get("bps")),
                operating_cashflow=operating_cashflow,
            ))
        return results

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
