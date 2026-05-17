"""
美股 yfinance Adapter

职责：将 YFinanceUSProvider 返回的原始数据转换为 Schema 标准格式。
"""

from typing import Any

from app.data.sources.base.adapter import BaseAdapter
from app.data.schema.stock_basic_info import StockBasicInfoSchema
from app.data.schema.stock_daily_quotes import StockDailyQuoteSchema


class YFinanceUSAdapter(BaseAdapter):
    """美股 yfinance Adapter"""

    def adapt_basic_info(self, row: Any) -> StockBasicInfoSchema:
        get = row.get if hasattr(row, "get") else lambda k: getattr(row, k, None)
        symbol = str(get("symbol", "") or get("ticker", "")).upper()
        name = get("longName") or get("shortName") or get("name", "")
        market_cap = self._safe_float(get("marketCap"))
        return StockBasicInfoSchema(
            symbol=symbol,
            full_symbol=symbol,
            name=name,
            market="US",
            exchange=get("exchange", ""),
            currency=get("currency", "USD"),
            industry=get("industry"),
            sector=get("sector"),
            total_mv=market_cap / 1e8 if market_cap else None,
            pe=self._safe_float(get("trailingPE")),
            pb=self._safe_float(get("priceToBook")),
            ps=self._safe_float(get("priceToSalesTrailing12Months")),
            shares_outstanding=self._safe_float(get("sharesOutstanding")),
            float_shares=self._safe_float(get("floatShares")),
            employees=self._safe_float(get("fullTimeEmployees")),
            website=get("website"),
            description=get("longBusinessSummary"),
            data_source="yfinance_us",
            updated_at="",
        )

    def adapt_daily_quote(self, row: Any) -> StockDailyQuoteSchema:
        get = row.get if hasattr(row, "get") else lambda k: getattr(row, k, None)
        symbol = str(get("symbol", "") or get("ticker", "")).upper()
        close = self._safe_float(get("Close") or get("close"))
        pre_close = self._safe_float(get("pre_close"))
        change = self._safe_float(get("change"))
        pct_chg = self._safe_float(get("pct_chg"))
        if change is None and close is not None and pre_close is not None:
            change = round(close - pre_close, 4)
        if pct_chg is None and close is not None and pre_close is not None and pre_close != 0:
            pct_chg = round((close - pre_close) / pre_close * 100, 4)

        trade_date = get("trade_date") or get("date") or get("Date")
        if trade_date is not None:
            trade_date = str(trade_date)[:10]

        return StockDailyQuoteSchema(
            symbol=symbol,
            full_symbol=symbol,
            trade_date=trade_date or "",
            period="daily",
            open=self._safe_float(get("Open") or get("open")),
            high=self._safe_float(get("High") or get("high")),
            low=self._safe_float(get("Low") or get("low")),
            close=close,
            pre_close=pre_close,
            volume=self._safe_float(get("Volume") or get("volume")),
            amount=self._safe_float(get("amount")),
            change=change,
            pct_chg=pct_chg,
            data_source="yfinance_us",
            created_at="",
            updated_at="",
        )
