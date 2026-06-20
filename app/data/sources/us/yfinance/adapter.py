"""yfinance US Adapter — 原始数据 → 标准 Schema。

大写 ticker，adj_close，dividends/splits → corporate_actions。
"""

import logging
from typing import Any, List

import pandas as pd

from app.data.sources.base.adapter import BaseAdapter
from app.data.schema.base.types import _safe_float, _parse_date
from app.data.schema.domains.basic_info import StockBasicInfoSchema
from app.data.schema.domains.daily_quotes import DailyQuotesSchema
from app.data.schema.domains.daily_indicators import DailyIndicatorsSchema
from app.data.schema.domains.corporate_actions import CorporateActionsSchema
from app.data.schema.domains.financial_data import FinancialDataSchema
from app.data.schema.domains.market_quotes import MarketQuotesSchema
from app.data.schema.domains.stock_news import StockNewsSchema

logger = logging.getLogger(__name__)


class YFinanceUSAdapter(BaseAdapter):
    """yfinance 美股数据标准化适配器。"""

    def __init__(self, provider=None):
        super().__init__(provider=provider, market="US", source_name="yfinance")

    def adapt_basic_info(self, raw: Any) -> List[StockBasicInfoSchema]:
        if isinstance(raw, dict):
            symbol = str(raw.get("symbol", raw.get("ticker", ""))).upper()
            return [StockBasicInfoSchema(
                symbol=symbol,
                market="US",
                data_source="yfinance",
                name=raw.get("longName") or raw.get("shortName", ""),
                full_symbol=symbol,
                exchange=raw.get("exchange", ""),
                industry=raw.get("industry", ""),
                currency=raw.get("currency", "USD"),
            )]
        return []

    def adapt_daily_quotes(self, raw: Any) -> List[DailyQuotesSchema]:
        df = raw if isinstance(raw, pd.DataFrame) else pd.DataFrame(raw)
        if df.empty:
            return []
        results = []
        for idx, row in df.iterrows():
            get = row.get
            symbol = str(get("symbol", "")).upper()
            trade_date = str(idx)[:10] if hasattr(idx, "strftime") else _parse_date(get("trade_date", ""))
            if not trade_date:
                continue

            close = _safe_float(get("Close"))
            pre_close = _safe_float(get("pre_close"))
            change = _safe_float(get("change"))
            pct_chg = _safe_float(get("pct_chg"))

            results.append(DailyQuotesSchema(
                symbol=symbol,
                market="US",
                data_source="yfinance",
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
                symbol=str(get("symbol", "")).upper(),
                market="US",
                data_source="yfinance",
                ex_date=ex_date,
                action_type=action_type,
                amount=_safe_float(get("amount")),
                currency="USD",
                ratio_from=_safe_float(get("ratio")),
            ))
        return results

    def adapt_financial_data(self, raw: Any) -> List[FinancialDataSchema]:
        df = raw if isinstance(raw, pd.DataFrame) else pd.DataFrame(raw)
        if df.empty:
            return []
        # yfinance financials: 行是指标名，列是日期
        default_symbol = str(df.attrs.get("symbol", "")).upper() if hasattr(df, "attrs") else ""
        results = []
        for col in df.columns:
            try:
                report_period = str(col)[:10]
                col_data = df[col]
                results.append(FinancialDataSchema(
                    symbol=default_symbol,
                    market="US",
                    data_source="yfinance",
                    report_period=report_period,
                    statement_type="income",
                    revenue=_safe_float(col_data.get("Total Revenue")),
                    net_profit=_safe_float(col_data.get("Net Income")),
                    operating_cashflow=_safe_float(col_data.get("Operating Cash Flow")),
                ))
            except Exception as e:
                logger.debug(f"解析财务数据行失败: {e}")
                continue
        return results

    def adapt_market_quotes(self, raw: Any) -> List[MarketQuotesSchema]:
        df = raw if isinstance(raw, pd.DataFrame) else pd.DataFrame(raw)
        if df.empty:
            return []
        results = []
        for _, row in df.iterrows():
            get = row.get
            results.append(MarketQuotesSchema(
                symbol=str(get("symbol", "")).upper(),
                market="US",
                data_source="yfinance",
                last_price=_safe_float(get("price")),
                last_volume=_safe_float(get("volume")),
            ))
        return results

    def adapt_daily_indicators(self, raw: Any) -> List[DailyIndicatorsSchema]:
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
            results.append(DailyIndicatorsSchema(
                symbol=symbol,
                market="US",
                data_source="yfinance",
                trade_date=trade_date,
                pe_ttm=_safe_float(get("pe_ttm") or get("trailingPE")),
                pb=_safe_float(get("pb") or get("priceToBook")),
                ps_ttm=_safe_float(get("ps_ttm") or get("priceToSalesTrailing12Months")),
                dividend_yield=_safe_float(get("dividend_yield") or get("dividendYield")),
                market_cap=_safe_float(get("market_cap") or get("marketCap")),
                float_market_cap=_safe_float(get("float_market_cap") or get("floatShares")),
                shares_outstanding=_safe_float(get("shares_outstanding") or get("sharesOutstanding")),
                float_shares=_safe_float(get("float_shares") or get("floatShares")),
            ))
        return results

    def adapt_news(self, raw: Any) -> List[StockNewsSchema]:
        df = raw if isinstance(raw, pd.DataFrame) else pd.DataFrame(raw)
        if df.empty:
            return []
        results = []
        for _, row in df.iterrows():
            get = row.get
            title = get("title", "") or get("标题", "")
            publish_time = (
                get("publish_time", "") or get("发布时间", "") or get("datetime", "")
            )
            content_hash = StockNewsSchema.compute_hash(title, str(publish_time)) if title else None
            raw_symbol = str(get("symbol", ""))
            results.append(StockNewsSchema(
                symbol=raw_symbol.upper() if raw_symbol else "",
                market="US",
                data_source="yfinance",
                title=title,
                content=get("content") or get("摘要", "") or get("summary"),
                content_hash=content_hash,
                source=get("source") or get("来源", "") or get("publisher", ""),
                publish_time=publish_time,
                url=get("url") or get("链接", "") or get("link"),
            ))
        return results
