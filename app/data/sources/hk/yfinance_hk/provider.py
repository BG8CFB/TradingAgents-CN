"""yfinance HK Provider — 调用 yfinance 库获取港股数据。"""

import asyncio
import logging

import pandas as pd

from app.data.sources.base.provider import BaseProvider

logger = logging.getLogger(__name__)


def _to_yfinance_symbol(symbol: str) -> str:
    """港股代码转 yfinance 格式: 00700 -> 0700.HK"""
    code = str(symbol).replace(".HK", "").lstrip("0").zfill(4)
    return f"{code}.HK"


class YFinanceHKProvider(BaseProvider):
    """yfinance 港股数据源 Provider。"""

    def __init__(self):
        super().__init__(name="yfinance_hk", market="HK")

    async def connect(self) -> bool:
        self.connected = True
        return True

    def is_available(self) -> bool:
        try:
            import yfinance as yf  # noqa: F401
            return True
        except ImportError:
            return False

    async def get_stock_list(self, **kwargs) -> pd.DataFrame:
        raise NotImplementedError(f"{self.name} 不支持 get_stock_list")

    async def get_daily_quotes(
        self, symbol: str, start_date: str, end_date: str, **kwargs
    ) -> pd.DataFrame:
        try:
            import yfinance as yf
            hk_symbol = _to_yfinance_symbol(symbol)
            end = pd.to_datetime(end_date) + pd.DateOffset(days=1)

            def _fetch():
                ticker = yf.Ticker(hk_symbol)
                return ticker.history(start=start_date, end=end.strftime("%Y-%m-%d"))

            df = await asyncio.to_thread(_fetch)
            if df is not None and not df.empty:
                df["symbol"] = symbol.zfill(5)
                logger.info(f"yfinance-HK 行情: {symbol} {len(df)} 条")
            return df
        except Exception as e:
            logger.error(f"yfinance-HK 行情失败 {symbol}: {e}")
            return None

    async def get_corporate_actions(
        self, symbol: str, start_date: str, end_date: str, **kwargs
    ) -> pd.DataFrame:
        try:
            import yfinance as yf
            hk_symbol = _to_yfinance_symbol(symbol)

            def _fetch():
                ticker = yf.Ticker(hk_symbol)
                actions = ticker.actions
                dividends = ticker.dividends
                splits = ticker.splits
                return {"actions": actions, "dividends": dividends, "splits": splits}

            result = await asyncio.to_thread(_fetch)
            if not result:
                return None

            # 合并 dividends 和 splits
            records = []
            if result["dividends"] is not None and not result["dividends"].empty:
                for date, val in result["dividends"].items():
                    if start_date <= str(date)[:10] <= end_date:
                        records.append({
                            "date": date, "action_type": "cash_dividend",
                            "amount": val, "symbol": symbol,
                        })
            if result["splits"] is not None and not result["splits"].empty:
                for date, val in result["splits"].items():
                    if start_date <= str(date)[:10] <= end_date:
                        records.append({
                            "date": date, "action_type": "stock_split",
                            "ratio": val, "symbol": symbol,
                        })
            return pd.DataFrame(records) if records else None
        except Exception as e:
            logger.debug(f"yfinance-HK 公司行为失败 {symbol}: {e}")
            return None

    async def get_financial_data(
        self, symbol: str, start_date: str, end_date: str,
        statement_type: str = "", **kwargs
    ) -> pd.DataFrame:
        try:
            import yfinance as yf
            hk_symbol = _to_yfinance_symbol(symbol)

            def _fetch():
                ticker = yf.Ticker(hk_symbol)
                return ticker.financials

            df = await asyncio.to_thread(_fetch)
            if df is not None and not df.empty:
                df.attrs["symbol"] = symbol.zfill(5)
            return df
        except Exception as e:
            logger.debug(f"yfinance-HK 财务数据失败 {symbol}: {e}")
            return None
