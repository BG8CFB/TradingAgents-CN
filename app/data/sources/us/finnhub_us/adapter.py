"""
美股 Finnhub Adapter

职责：将 FinnhubUSProvider 返回的原始数据转换为 Schema 标准格式。
"""

from typing import Any, Dict, Optional

from app.data.sources.base.adapter import BaseAdapter
from app.data.schema.stock_basic_info import StockBasicInfoSchema
from app.data.schema.stock_daily_quotes import StockDailyQuoteSchema
from app.data.schema.stock_news import NewsSchema


class FinnhubUSAdapter(BaseAdapter):
    """美股 Finnhub Adapter"""

    def adapt_basic_info(self, row: Any) -> StockBasicInfoSchema:
        get = row.get if hasattr(row, "get") else lambda k: getattr(row, k, None)
        symbol = str(get("ticker", "") or get("symbol", "")).upper()
        name = get("name", "")
        market_cap_raw = self._safe_float(get("marketCapitalization"))
        market_cap = market_cap_raw * 1e6 if market_cap_raw else None

        return StockBasicInfoSchema(
            symbol=symbol,
            full_symbol=symbol,
            name=name,
            market="US",
            exchange=get("exchange", ""),
            currency=get("currency", "USD"),
            industry=get("finnhubIndustry"),
            total_mv=market_cap / 1e8 if market_cap else None,
            shares_outstanding=self._safe_float(get("shareOutstanding")) * 1e6
            if get("shareOutstanding") else None,
            data_source="finnhub_us",
            updated_at="",
        )

    def adapt_daily_quote(self, row: Any) -> StockDailyQuoteSchema:
        get = row.get if hasattr(row, "get") else lambda k: getattr(row, k, None)
        symbol = str(get("symbol", "") or get("ticker", "")).upper()
        close = self._safe_float(get("close") or get("current_price") or get("c"))
        pre_close = self._safe_float(get("pre_close") or get("previous_close") or get("pc"))
        change = self._safe_float(get("change") or get("d"))
        pct_chg = self._safe_float(get("pct_change") or get("change_percent") or get("dp"))
        trade_date = str(get("trade_date", "") or get("date", ""))

        return StockDailyQuoteSchema(
            symbol=symbol,
            full_symbol=symbol,
            trade_date=trade_date,
            period="daily",
            open=self._safe_float(get("open") or get("o")),
            high=self._safe_float(get("high") or get("h")),
            low=self._safe_float(get("low") or get("l")),
            close=close,
            pre_close=pre_close,
            volume=self._safe_float(get("volume") or get("v")),
            amount=None,
            change=change,
            pct_chg=pct_chg,
            data_source="finnhub_us",
            created_at="",
            updated_at="",
        )

    def adapt_news(self, raw: Dict[str, Any]) -> Optional[NewsSchema]:
        from datetime import datetime

        timestamp = raw.get("datetime", 0)
        pub_time = datetime.fromtimestamp(timestamp).isoformat() if timestamp else ""
        return NewsSchema(
            symbol=raw.get("related", "").upper(),
            title=raw.get("headline", ""),
            content=raw.get("summary", ""),
            url=raw.get("url", ""),
            source=raw.get("source", ""),
            published_at=pub_time,
            data_source="finnhub_us",
            updated_at="",
        )
