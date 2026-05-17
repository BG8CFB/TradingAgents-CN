"""
BaoStock 数据源 Provider — 包装现有 BaoStockProvider
"""

import logging
from typing import Any, Dict, List, Optional

import pandas as pd

from app.data.sources.base.provider import BaseProvider

logger = logging.getLogger(__name__)


class BaoStockSourceProvider(BaseProvider):
    """BaoStock 数据源 Provider"""

    def __init__(self):
        super().__init__(name="baostock", market="CN")
        self._provider = None

    def _get_provider(self):
        if self._provider is None:
            from app.data.providers.china.baostock import BaoStockProvider
            self._provider = BaoStockProvider()
        return self._provider

    async def connect(self) -> bool:
        try:
            provider = self._get_provider()
            self.connected = await provider.connect()
            return self.connected
        except Exception as e:
            logger.error(f"BaoStock 连接失败: {e}")
            return False

    def is_available(self) -> bool:
        try:
            self._get_provider()
            return True
        except Exception:
            return False

    async def get_stock_list(self, market: str = None) -> Optional[pd.DataFrame]:
        provider = self._get_provider()
        result = await provider.get_stock_list()
        if isinstance(result, list):
            return pd.DataFrame(result) if result else None
        return result

    async def get_stock_basic_info(self, symbol: str) -> Optional[Dict[str, Any]]:
        provider = self._get_provider()
        return await provider.get_stock_basic_info(code=symbol)

    async def get_daily_quotes(
        self, symbol: str, start_date: str, end_date: str
    ) -> Optional[pd.DataFrame]:
        provider = self._get_provider()
        return await provider.get_historical_data(
            code=symbol, start_date=start_date, end_date=end_date
        )

    async def get_financial_data(self, symbol: str) -> Optional[pd.DataFrame]:
        provider = self._get_provider()
        data = await provider.get_financial_data(code=symbol)
        if isinstance(data, dict):
            return pd.DataFrame([data]) if data else None
        return data
