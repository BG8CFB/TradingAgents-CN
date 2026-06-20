"""
基本面报告服务

通过新架构 DataInterface 提供基本面数据获取功能。
"""

import logging
from typing import Dict, Optional

import pandas as pd

from app.core.async_utils import run_async
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
        result = await self.di.read("CN", "daily_quotes", symbol=symbol, start_date=start_date, end_date=end_date)
        data = result.get("data")
        if data and isinstance(data, list):
            return pd.DataFrame(data)
        return None

    async def get_fundamentals(self, symbol: str) -> Optional[Dict]:
        result = await self.di.read("CN", "financial_data", symbol=symbol)
        return result.get("data")


_provider_instance: Optional[FundamentalsProvider] = None


def get_fundamentals_provider() -> FundamentalsProvider:
    global _provider_instance
    if _provider_instance is None:
        _provider_instance = FundamentalsProvider()
    return _provider_instance


def get_china_stock_data_cached(symbol: str, start_date: str, end_date: str) -> Optional[pd.DataFrame]:
    """同步获取基本面行情数据。

    通过 :func:`run_async` 统一处理同步→异步桥接：
    - worker thread 中调用 → run_coroutine_threadsafe 调度到主循环
    - 纯脚本中调用 → asyncio.run 创建新循环
    """
    provider = get_fundamentals_provider()
    try:
        return run_async(provider.get_stock_data(symbol, start_date, end_date))
    except Exception as e:
        logger.debug(f"获取基本面数据失败: {e}")
        return None


def get_china_fundamentals_cached(symbol: str) -> Optional[Dict]:
    """同步获取基本面摘要（同 get_china_stock_data_cached 桥接策略）。"""
    provider = get_fundamentals_provider()
    try:
        return run_async(provider.get_fundamentals(symbol))
    except Exception as e:
        logger.debug(f"获取基本面摘要失败: {e}")
        return None


__all__ = [
    "FundamentalsProvider",
    "get_fundamentals_provider",
    "get_china_stock_data_cached",
    "get_china_fundamentals_cached",
]
