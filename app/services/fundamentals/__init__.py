"""
基本面报告服务

通过新架构 DataInterface 提供基本面数据获取功能。
"""

import asyncio
import logging
from typing import Any, Dict, List, Optional

import pandas as pd

from app.data.core.interface import DataInterface

logger = logging.getLogger(__name__)


class FundamentalsProvider:
    """基本面数据提供器 — 委托到新架构 DataInterface。"""

    def __init__(self):
        self._di = None

    @property
    def di(self):
        if self._di is None:
            self._di = DataInterface.get_instance()
        return self._di

    async def get_stock_data(self, symbol: str, start_date: str, end_date: str) -> Optional[pd.DataFrame]:
        result = await self.di.read("CN", symbol, "daily_quotes", start_date=start_date, end_date=end_date)
        data = result.get("data")
        if data and isinstance(data, list):
            return pd.DataFrame(data)
        return None

    async def get_fundamentals(self, symbol: str) -> Optional[Dict]:
        result = await self.di.read("CN", symbol, "financial_data")
        return result.get("data")


_provider_instance: Optional[FundamentalsProvider] = None


def get_fundamentals_provider() -> FundamentalsProvider:
    global _provider_instance
    if _provider_instance is None:
        _provider_instance = FundamentalsProvider()
    return _provider_instance


def get_china_stock_data_cached(symbol: str, start_date: str, end_date: str) -> Optional[pd.DataFrame]:
    provider = get_fundamentals_provider()
    try:
        return asyncio.run(provider.get_stock_data(symbol, start_date, end_date))
    except Exception:
        return None


def get_china_fundamentals_cached(symbol: str) -> Optional[Dict]:
    provider = get_fundamentals_provider()
    try:
        return asyncio.run(provider.get_fundamentals(symbol))
    except Exception:
        return None


__all__ = [
    "FundamentalsProvider",
    "get_fundamentals_provider",
    "get_china_stock_data_cached",
    "get_china_fundamentals_cached",
]
