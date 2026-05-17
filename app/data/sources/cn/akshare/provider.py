"""
AKShare 数据源 Provider — 包装现有 AKShareProvider
"""

import logging
from typing import Any, Dict, List, Optional

import pandas as pd

from app.data.sources.base.provider import BaseProvider

logger = logging.getLogger(__name__)


class AKShareSourceProvider(BaseProvider):
    """AKShare 数据源 Provider"""

    def __init__(self):
        super().__init__(name="akshare", market="CN")
        self._provider = None

    def _get_provider(self):
        if self._provider is None:
            from app.data.providers.china.akshare import AKShareProvider
            self._provider = AKShareProvider()
        return self._provider

    async def connect(self) -> bool:
        try:
            self._get_provider()
            self.connected = True
            return True
        except Exception as e:
            logger.error(f"AKShare 连接失败: {e}")
            return False

    def is_available(self) -> bool:
        try:
            self._get_provider()
            return True
        except Exception:
            return False

    async def get_stock_list(self, market: str = None) -> Optional[pd.DataFrame]:
        provider = self._get_provider()
        return await provider.get_stock_list()

    async def get_stock_basic_info(self, symbol: str) -> Optional[Dict[str, Any]]:
        provider = self._get_provider()
        return await provider.get_stock_basic_info(symbol=symbol)

    async def get_daily_quotes(
        self, symbol: str, start_date: str, end_date: str
    ) -> Optional[pd.DataFrame]:
        provider = self._get_provider()
        return await provider.get_historical_data(
            code=symbol, start_date=start_date, end_date=end_date
        )

    async def get_realtime_quotes(self) -> Optional[Dict[str, Dict[str, Any]]]:
        provider = self._get_provider()
        return await provider.get_stock_quotes_batch()

    async def get_news(
        self, symbol: str, days: int = 2, limit: int = 50
    ) -> Optional[List[Dict[str, Any]]]:
        provider = self._get_provider()
        return await provider.get_stock_news(symbol=symbol, limit=limit)
