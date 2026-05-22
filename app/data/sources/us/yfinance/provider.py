"""yfinance US Provider — 全市场主源，覆盖所有美股。"""

import asyncio
import logging
from typing import Optional

import pandas as pd

from app.data.sources.base.provider import BaseProvider

logger = logging.getLogger(__name__)


class YFinanceUSProvider(BaseProvider):
    """yfinance 美股数据源 Provider。"""

    def __init__(self):
        super().__init__(name="yfinance", market="US")

    async def connect(self) -> bool:
        self.connected = True
        return True

    def is_available(self) -> bool:
        try:
            import yfinance as yf  # noqa: F401
            return True
        except ImportError:
            return False

    async def get_stock_list(self, **kwargs) -> Optional[pd.DataFrame]:
        # yfinance 不支持全市场列表，返回 None（由 Finnhub 承担）
        return None

    async def get_daily_quotes(
        self, symbol: str, start_date: str, end_date: str, **kwargs
    ) -> Optional[pd.DataFrame]:
        try:
            import yfinance as yf
            ticker = symbol.upper()
            end = pd.to_datetime(end_date) + pd.DateOffset(days=1)

            def _fetch():
                t = yf.Ticker(ticker)
                return t.history(start=start_date, end=end.strftime("%Y-%m-%d"))

            df = await asyncio.to_thread(_fetch)
            if df is not None and not df.empty:
                # 添加 symbol 列
                df["symbol"] = ticker
            return df
        except Exception as e:
            logger.error(f"yfinance-US 行情失败 {symbol}: {e}")
            return None

    async def get_corporate_actions(
        self, symbol: str, start_date: str, end_date: str, **kwargs
    ) -> Optional[pd.DataFrame]:
        try:
            import yfinance as yf
            ticker = symbol.upper()

            def _fetch():
                t = yf.Ticker(ticker)
                return {"dividends": t.dividends, "splits": t.splits}

            result = await asyncio.to_thread(_fetch)
            records = []
            divs = result.get("dividends")
            if divs is not None and not divs.empty:
                for date, val in divs.items():
                    ds = str(date)[:10]
                    if start_date <= ds <= end_date:
                        records.append({
                            "date": ds, "action_type": "cash_dividend",
                            "amount": val, "symbol": ticker,
                        })
            splits = result.get("splits")
            if splits is not None and not splits.empty:
                for date, val in splits.items():
                    ds = str(date)[:10]
                    if start_date <= ds <= end_date:
                        action = "stock_split" if val > 1 else "reverse_split"
                        records.append({
                            "date": ds, "action_type": action,
                            "ratio": val, "symbol": ticker,
                        })
            return pd.DataFrame(records) if records else None
        except Exception as e:
            logger.debug(f"yfinance-US 公司行为失败 {symbol}: {e}")
            return None

    async def get_daily_indicators(
        self, symbol: str, start_date: str, end_date: str, **kwargs
    ) -> Optional[pd.DataFrame]:
        # yfinance 不直接提供 PE/PB 等指标，通过 info 获取
        return None

    async def get_financial_data(
        self, symbol: str, start_date: str, end_date: str,
        statement_type: str = "", **kwargs
    ) -> Optional[pd.DataFrame]:
        try:
            import yfinance as yf
            ticker = symbol.upper()

            def _fetch():
                t = yf.Ticker(ticker)
                return t.financials

            df = await asyncio.to_thread(_fetch)
            if df is not None and not df.empty:
                df.attrs["symbol"] = ticker
            return df
        except Exception as e:
            logger.debug(f"yfinance-US 财务数据失败 {symbol}: {e}")
            return None

    async def get_market_quotes(
        self, symbols=None, **kwargs
    ) -> Optional[pd.DataFrame]:
        # 单只快照
        if not symbols or len(symbols) != 1:
            return None
        symbol = symbols[0].upper()
        try:
            import yfinance as yf

            def _fetch():
                t = yf.Ticker(symbol)
                info = t.info
                if not info:
                    return None
                return pd.DataFrame([{
                    "symbol": symbol,
                    "price": info.get("currentPrice") or info.get("regularMarketPrice"),
                    "volume": info.get("volume"),
                    "market_cap": info.get("marketCap"),
                }])

            return await asyncio.to_thread(_fetch)
        except Exception as e:
            logger.debug(f"yfinance-US 快照失败 {symbol}: {e}")
            return None
