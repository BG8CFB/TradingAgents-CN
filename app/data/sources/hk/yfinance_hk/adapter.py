"""
港股 yfinance Adapter

职责：将 YFinanceHKProvider 返回的原始数据转换为 Schema 标准格式。
"""

from typing import Any

from app.data.sources.base.adapter import BaseAdapter
from app.data.schema.stock_basic_info import StockBasicInfoSchema
from app.data.schema.stock_daily_quotes import StockDailyQuoteSchema
from app.data.schema.base import get_full_symbol


class YFinanceHKAdapter(BaseAdapter):
    """港股 yfinance Adapter"""

    def adapt_basic_info(self, row: Any) -> StockBasicInfoSchema:
        get = row.get if hasattr(row, 'get') else lambda k: getattr(row, k, None)
        symbol = str(get("symbol", "") or get("code", ""))
        return StockBasicInfoSchema(
            symbol=symbol,
            full_symbol=get_full_symbol(symbol, "HK"),
            name=get("name", ""),
            market="HK",
            exchange="HKG",
            currency="HKD",
            industry=get("industry"),
            total_mv=self._safe_float(get("total_mv")),
            pe=self._safe_float(get("pe")),
            pb=self._safe_float(get("pb")),
            sector=get("sector"),
            data_source="yfinance_hk",
            updated_at=get("updated_at", ""),
        )

    def adapt_daily_quote(self, row: Any) -> StockDailyQuoteSchema:
        get = row.get
        symbol = str(get("symbol", "") or get("code", ""))
        close = self._safe_float(get("close"))
        pre_close = self._safe_float(get("pre_close"))
        change = self._safe_float(get("change"))
        pct_chg = self._safe_float(get("pct_chg"))
        if change is None and close is not None and pre_close is not None:
            change = round(close - pre_close, 4)
        if pct_chg is None and close is not None and pre_close is not None and pre_close != 0:
            pct_chg = round((close - pre_close) / pre_close * 100, 4)

        return StockDailyQuoteSchema(
            symbol=symbol,
            full_symbol=get_full_symbol(symbol, "HK"),
            trade_date=str(get("trade_date", ""))[:10],
            period="daily",
            open=self._safe_float(get("open")),
            high=self._safe_float(get("high")),
            low=self._safe_float(get("low")),
            close=close,
            pre_close=pre_close,
            volume=self._safe_float(get("volume")),
            amount=self._safe_float(get("amount")),
            change=change,
            pct_chg=pct_chg,
            data_source="yfinance_hk",
            created_at=get("created_at", ""),
            updated_at=get("updated_at", ""),
        )
