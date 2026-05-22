"""AKShare HK Provider — 调用 AKShare 港股 API。"""

import asyncio
import logging
from typing import Optional

import pandas as pd

from app.data.sources.base.provider import BaseProvider

logger = logging.getLogger(__name__)


def _normalize_hk_symbol(symbol: str) -> str:
    """标准化港股代码为 5 位数字。"""
    return str(symbol).replace(".HK", "").lstrip("0").zfill(5)


class AKShareHKProvider(BaseProvider):
    """AKShare 港股数据源 Provider。"""

    def __init__(self):
        super().__init__(name="akshare_hk", market="HK")

    async def connect(self) -> bool:
        self.connected = True
        return True

    def is_available(self) -> bool:
        try:
            import akshare as ak  # noqa: F401
            return True
        except ImportError:
            return False

    async def get_stock_list(self, **kwargs) -> Optional[pd.DataFrame]:
        try:
            import akshare as ak
            df = await asyncio.to_thread(ak.stock_hk_spot_em)
            return df
        except Exception as e:
            logger.error(f"AKShare-HK 股票列表失败: {e}")
            return None

    async def get_daily_quotes(
        self, symbol: str, start_date: str, end_date: str, **kwargs
    ) -> Optional[pd.DataFrame]:
        try:
            import akshare as ak
            normalized = _normalize_hk_symbol(symbol)
            df = await asyncio.to_thread(ak.stock_hk_daily, symbol=normalized, adjust="qfq")
            if df is None or df.empty:
                return None
            # 日期过滤
            date_col = "日期" if "日期" in df.columns else "date"
            if date_col in df.columns:
                df[date_col] = pd.to_datetime(df[date_col])
                df = df[(df[date_col] >= start_date) & (df[date_col] <= end_date)]
            return df
        except Exception as e:
            logger.error(f"AKShare-HK 行情失败 {symbol}: {e}")
            return None

    async def get_corporate_actions(
        self, symbol: str, start_date: str, end_date: str, **kwargs
    ) -> Optional[pd.DataFrame]:
        try:
            import akshare as ak
            normalized = _normalize_hk_symbol(symbol)
            df = await asyncio.to_thread(ak.stock_hk_ggcgy_em, symbol=normalized)
            return df
        except Exception as e:
            logger.debug(f"AKShare-HK 公司行为失败 {symbol}: {e}")
            return None

    async def get_news(
        self, symbol: str, start_date: str, end_date: str, **kwargs
    ) -> Optional[pd.DataFrame]:
        try:
            import akshare as ak
            normalized = _normalize_hk_symbol(symbol)
            df = await asyncio.to_thread(ak.stock_hk_notice_report, symbol=normalized)
            return df
        except Exception as e:
            logger.debug(f"AKShare-HK 新闻失败 {symbol}: {e}")
            return None

    async def get_market_quotes(
        self, symbols=None, **kwargs
    ) -> Optional[pd.DataFrame]:
        return await self.get_stock_list()
