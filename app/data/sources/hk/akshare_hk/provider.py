"""
港股 AKShare Provider

独立调用 AKShare 港股 API。
不再委托旧版 providers/hk/improved_hk.py。
"""

import asyncio
import logging
from typing import Any, Dict, Optional

import pandas as pd

from app.data.sources.base.provider import BaseProvider

logger = logging.getLogger(__name__)


class AKShareHKProvider(BaseProvider):
    """港股 AKShare Provider"""

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

    async def get_stock_list(self) -> Optional[pd.DataFrame]:
        try:
            import akshare as ak

            def _fetch():
                return ak.stock_hk_spot_em()

            df = await asyncio.to_thread(_fetch)
            if df is not None and not df.empty:
                logger.info(f"AKShare-HK 股票列表: {len(df)} 只")
            return df
        except Exception as e:
            logger.error(f"AKShare-HK 股票列表失败: {e}")
            return None

    async def get_stock_basic_info(self, symbol: str) -> Optional[Dict[str, Any]]:
        try:
            import akshare as ak
            normalized = _normalize_hk_symbol(symbol)

            def _fetch():
                return ak.stock_hk_spot_em()

            df = await asyncio.to_thread(_fetch)
            if df is not None and not df.empty:
                code_col = "代码" if "代码" in df.columns else df.columns[0]
                match = df[df[code_col].astype(str).str.contains(normalized)]
                if not match.empty:
                    return match.iloc[0].to_dict()
            return None
        except Exception as e:
            logger.error(f"AKShare-HK 基础信息失败 {symbol}: {e}")
            return None

    async def get_daily_quotes(
        self, symbol: str, start_date: str, end_date: str
    ) -> Optional[pd.DataFrame]:
        try:
            import akshare as ak
            normalized = _normalize_hk_symbol(symbol)

            def _fetch():
                return ak.stock_hk_daily(symbol=normalized, adjust="qfq")

            df = await asyncio.to_thread(_fetch)
            if df is None or df.empty:
                return None

            # 日期过滤
            if "date" in df.columns:
                df["date"] = pd.to_datetime(df["date"])
                df = df[(df["date"] >= start_date) & (df["date"] <= end_date)]
            elif "日期" in df.columns:
                df["日期"] = pd.to_datetime(df["日期"])
                df = df[(df["日期"] >= start_date) & (df["日期"] <= end_date)]

            if df.empty:
                return None
            logger.info(f"AKShare-HK 行情: {symbol} {len(df)} 条")
            return df
        except Exception as e:
            logger.error(f"AKShare-HK 行情失败 {symbol}: {e}")
            return None


def _normalize_hk_symbol(symbol: str) -> str:
    """标准化港股代码为 5 位数字"""
    return str(symbol).replace(".HK", "").lstrip("0").zfill(5)
