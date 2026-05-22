"""Alpha Vantage US Adapter — 原始数据 → 标准 Schema。"""

import logging
from typing import Any, List

import pandas as pd

from app.data.sources.base.adapter import BaseAdapter
from app.data.schema.base.types import _safe_float, _parse_date
from app.data.schema.domains.daily_quotes import DailyQuotesSchema
from app.data.schema.domains.corporate_actions import CorporateActionsSchema
from app.data.schema.domains.financial_data import FinancialDataSchema

logger = logging.getLogger(__name__)


class AlphaVantageUSAdapter(BaseAdapter):
    """Alpha Vantage 美股数据标准化适配器。"""

    def __init__(self, provider=None):
        super().__init__(provider=provider, market="US", source_name="alpha_vantage")

    def adapt_daily_quotes(self, raw: Any) -> List[DailyQuotesSchema]:
        df = raw if isinstance(raw, pd.DataFrame) else pd.DataFrame(raw)
        if df.empty:
            return []
        results = []
        for _, row in df.iterrows():
            get = row.get
            symbol = str(get("symbol", "")).upper()
            trade_date = _parse_date(get("trade_date", ""))
            if not trade_date:
                continue
            results.append(DailyQuotesSchema(
                symbol=symbol,
                market="US",
                data_source="alpha_vantage",
                trade_date=trade_date,
                period="daily",
                open=_safe_float(get("open")),
                high=_safe_float(get("high")),
                low=_safe_float(get("low")),
                close=_safe_float(get("close")),
                volume=_safe_float(get("volume")),
            ))
        return results

    def adapt_corporate_actions(self, raw: Any) -> List[CorporateActionsSchema]:
        df = raw if isinstance(raw, pd.DataFrame) else pd.DataFrame(raw)
        if df.empty:
            return []
        results = []
        for _, row in df.iterrows():
            get = row.get
            ex_date = _parse_date(str(get("date", ""))[:10])
            results.append(CorporateActionsSchema(
                symbol=str(get("symbol", "")).upper(),
                market="US",
                data_source="alpha_vantage",
                ex_date=ex_date,
                action_type=get("action_type", "cash_dividend"),
                amount=_safe_float(get("amount")),
                currency="USD",
            ))
        return results

    def adapt_financial_data(self, raw: Any) -> List[FinancialDataSchema]:
        df = raw if isinstance(raw, pd.DataFrame) else pd.DataFrame(raw)
        if df.empty:
            return []
        results = []
        for _, row in df.iterrows():
            get = row.get
            symbol = str(get("symbol", "")).upper()
            results.append(FinancialDataSchema(
                symbol=symbol,
                market="US",
                data_source="alpha_vantage",
                report_period=_parse_date(get("fiscalDateEnding")),
                revenue=_safe_float(get("totalRevenue")),
                net_profit=_safe_float(get("netIncome")),
                total_assets=_safe_float(get("totalAssets")),
                total_equity=_safe_float(get("totalShareholderEquity")),
                operating_cashflow=_safe_float(get("operatingIncome")),
                eps=_safe_float(get("eps")),
            ))
        return results
