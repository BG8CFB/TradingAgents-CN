"""
港股 yfinance Provider

独立调用 yfinance 库获取港股数据。
不再委托旧版 providers/hk/hk_stock.py。
"""

import asyncio
import logging
from typing import Any, Dict, Optional

import pandas as pd

from app.data.sources.base.provider import BaseProvider

logger = logging.getLogger(__name__)


class YFinanceHKProvider(BaseProvider):
    """港股 yfinance Provider"""

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

    async def get_stock_basic_info(self, symbol: str) -> Optional[Dict[str, Any]]:
        try:
            import yfinance as yf
            hk_symbol = _to_yfinance_symbol(symbol)

            def _fetch():
                ticker = yf.Ticker(hk_symbol)
                return ticker.info

            info = await asyncio.to_thread(_fetch)
            return info if info else None
        except Exception as e:
            logger.error(f"yfinance-HK 基础信息失败 {symbol}: {e}")
            return None

    async def get_daily_quotes(
        self, symbol: str, start_date: str, end_date: str
    ) -> Optional[pd.DataFrame]:
        try:
            import yfinance as yf
            hk_symbol = _to_yfinance_symbol(symbol)
            end = pd.to_datetime(end_date) + pd.DateOffset(days=1)

            def _fetch():
                ticker = yf.Ticker(hk_symbol)
                return ticker.history(start=start_date, end=end.strftime("%Y-%m-%d"))

            df = await asyncio.to_thread(_fetch)
            if df is not None and not df.empty:
                logger.info(f"yfinance-HK 行情: {symbol} {len(df)} 条")
            return df
        except Exception as e:
            logger.error(f"yfinance-HK 行情失败 {symbol}: {e}")
            return None


def _to_yfinance_symbol(symbol: str) -> str:
    """将港股代码转为 yfinance 格式: 00700 -> 0700.HK"""
    code = str(symbol).replace(".HK", "").lstrip("0").zfill(4)
    return f"{code}.HK"
