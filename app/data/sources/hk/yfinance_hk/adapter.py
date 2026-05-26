"""yfinance HK Adapter — 原始数据 → 标准 Schema。"""

import logging
from typing import Any, List

import pandas as pd

from app.data.sources.base.adapter import BaseAdapter
from app.data.schema.base.types import _safe_float, _parse_date
from app.data.schema.domains.basic_info import StockBasicInfoSchema
from app.data.schema.domains.daily_quotes import DailyQuotesSchema
from app.data.schema.domains.corporate_actions import CorporateActionsSchema
from app.data.schema.domains.financial_data import FinancialDataSchema

logger = logging.getLogger(__name__)


class YFinanceHKAdapter(BaseAdapter):
    """yfinance 港股数据标准化适配器。"""

    def __init__(self, provider=None):
        super().__init__(provider=provider, market="HK", source_name="yfinance_hk")

    def adapt_basic_info(self, raw: Any) -> List[StockBasicInfoSchema]:
        if isinstance(raw, dict):
            symbol = str(raw.get("symbol", "")).zfill(5)
            return [StockBasicInfoSchema(
                symbol=symbol,
                market="HK",
                data_source="yfinance_hk",
                name=raw.get("shortName", "") or raw.get("longName", ""),
                full_symbol=f"{symbol}.HK",
                exchange="HKEX",
                industry=raw.get("industry", ""),
                currency="HKD",
            )]
        df = raw if isinstance(raw, pd.DataFrame) else pd.DataFrame(raw)
        if df.empty:
            return []
        results = []
        for _, row in df.iterrows():
            symbol = str(row.get("symbol", "")).zfill(5)
            results.append(StockBasicInfoSchema(
                symbol=symbol,
                market="HK",
                data_source="yfinance_hk",
                name=row.get("name", ""),
                full_symbol=f"{symbol}.HK",
                exchange="HKEX",
                currency="HKD",
            ))
        return results

    def adapt_daily_quotes(self, raw: Any) -> List[DailyQuotesSchema]:
        df = raw if isinstance(raw, pd.DataFrame) else pd.DataFrame(raw)
        if df.empty:
            return []
        results = []
        for idx, row in df.iterrows():
            get = row.get
            trade_date = str(idx)[:10] if hasattr(idx, "strftime") else _parse_date(get("trade_date", ""))
            if not trade_date:
                continue

            close = _safe_float(get("Close"))
            pre_close = _safe_float(get("pre_close"))
            change = _safe_float(get("change"))
            pct_chg = _safe_float(get("pct_chg"))

            results.append(DailyQuotesSchema(
                symbol=str(get("symbol", "")).zfill(5),
                market="HK",
                data_source="yfinance_hk",
                trade_date=trade_date,
                period="daily",
                open=_safe_float(get("Open")),
                high=_safe_float(get("High")),
                low=_safe_float(get("Low")),
                close=close,
                pre_close=pre_close,
                change=change,
                pct_chg=pct_chg,
                volume=_safe_float(get("Volume")),
                amount=_safe_float(get("amount")),
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
            action_type = get("action_type", "unknown")

            results.append(CorporateActionsSchema(
                symbol=str(get("symbol", "")).zfill(5),
                market="HK",
                data_source="yfinance_hk",
                ex_date=ex_date,
                action_type=action_type,
                amount=_safe_float(get("amount")),
                currency="HKD",
                ratio_from=_safe_float(get("ratio")) if action_type == "stock_split" else None,
            ))
        return results

    def adapt_financial_data(self, raw: Any) -> List[FinancialDataSchema]:
        df = raw if isinstance(raw, pd.DataFrame) else pd.DataFrame(raw)
        if df.empty:
            return []
        default_symbol = str(df.attrs.get("symbol", "")).zfill(5) if hasattr(df, "attrs") else ""
        results = []
        for col in df.columns:
            try:
                report_period = str(col)[:10]
                row_data = df[col]
                results.append(FinancialDataSchema(
                    symbol=default_symbol,
                    market="HK",
                    data_source="yfinance_hk",
                    report_period=report_period,
                    statement_type="income",
                    revenue=_safe_float(row_data.get("Total Revenue")),
                    net_profit=_safe_float(row_data.get("Net Income")),
                ))
            except Exception as e:
                logger.debug(f"解析港股财务数据行失败: {e}")
                continue
        return results
