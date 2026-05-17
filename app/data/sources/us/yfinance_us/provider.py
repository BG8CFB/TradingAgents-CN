"""
美股 yfinance Provider

直接调用 yfinance 库获取美股数据。
"""

import logging
from typing import Any, Dict, List, Optional

import pandas as pd

from app.data.sources.base.provider import BaseProvider

logger = logging.getLogger(__name__)


class YFinanceUSProvider(BaseProvider):
    """美股 yfinance Provider"""

    def __init__(self):
        super().__init__(name="yfinance_us", market="US")

    async def connect(self) -> bool:
        self.connected = True
        return True

    def is_available(self) -> bool:
        try:
            import yfinance as yf  # noqa: F401
            return True
        except ImportError:
            return False

    async def get_stock_basic_info(self, symbol: str) -> Optional[Dict[str, Any]]:
        import yfinance as yf

        ticker = yf.Ticker(symbol.upper())
        info = ticker.info
        if not info:
            return None
        return info

    async def get_daily_quotes(
        self, symbol: str, start_date: str, end_date: str
    ) -> Optional[pd.DataFrame]:
        import yfinance as yf

        ticker = yf.Ticker(symbol.upper())
        end = pd.to_datetime(end_date) + pd.DateOffset(days=1)
        df = ticker.history(start=start_date, end=end.strftime("%Y-%m-%d"))
        return df if df is not None and not df.empty else None

    async def get_financial_data(self, symbol: str) -> Optional[Dict[str, Any]]:
        import yfinance as yf

        ticker = yf.Ticker(symbol.upper())
        result = {}
        try:
            income = ticker.financials
            if income is not None and not income.empty:
                result["income_stmt"] = income
        except Exception:
            pass
        try:
            balance = ticker.balance_sheet
            if balance is not None and not balance.empty:
                result["balance_sheet"] = balance
        except Exception:
            pass
        try:
            cashflow = ticker.cashflow
            if cashflow is not None and not cashflow.empty:
                result["cash_flow"] = cashflow
        except Exception:
            pass
        return result if result else None

    async def get_kline(
        self, symbol: str, period: str = "day", limit: int = 120
    ) -> Optional[List[Dict[str, Any]]]:
        import yfinance as yf

        period_map = {
            "day": "1d", "week": "1wk", "month": "1mo",
            "5m": "5m", "15m": "15m", "30m": "30m", "60m": "60m",
        }
        interval = period_map.get(period, "1d")
        ticker = yf.Ticker(symbol.upper())
        hist = ticker.history(period=f"{limit}d", interval=interval)
        if hist.empty:
            return None

        kline_data = []
        for date, row in hist.iterrows():
            date_str = date.strftime("%Y-%m-%d")
            kline_data.append({
                "date": date_str, "trade_date": date_str,
                "open": float(row["Open"]), "high": float(row["High"]),
                "low": float(row["Low"]), "close": float(row["Close"]),
                "volume": int(row["Volume"]),
            })
        return kline_data
