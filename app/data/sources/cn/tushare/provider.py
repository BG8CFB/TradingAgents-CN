"""
Tushare 数据源 Provider

包装现有 TushareProvider，复用全部 API 调用逻辑。
不重写 API 层，仅提供 BaseProvider 接口适配。
"""

import logging
from typing import Any, Dict, List, Optional

import pandas as pd

from app.data.sources.base.provider import BaseProvider

logger = logging.getLogger(__name__)


class TushareSourceProvider(BaseProvider):
    """
    Tushare 数据源 Provider —— 包装现有 TushareProvider

    所有 API 调用委托给 app.data.providers.china.tushare.TushareProvider。
    本类只做接口适配，不做字段映射或单位转换。
    """

    def __init__(self):
        super().__init__(name="tushare", market="CN")
        self._provider = None

    def _get_provider(self):
        """延迟初始化现有 TushareProvider"""
        if self._provider is None:
            from app.data.providers.china.tushare import get_tushare_provider
            self._provider = get_tushare_provider()
        return self._provider

    async def connect(self) -> bool:
        try:
            provider = self._get_provider()
            self.connected = await provider.connect()
            return self.connected
        except Exception as e:
            logger.error(f"Tushare 连接失败: {e}")
            self.connected = False
            return False

    def is_available(self) -> bool:
        try:
            provider = self._get_provider()
            return provider.is_available()
        except Exception:
            return False

    async def get_stock_list(self, market: str = None) -> Optional[pd.DataFrame]:
        provider = self._get_provider()
        return await provider.get_stock_list(market=market)

    async def get_stock_basic_info(self, symbol: str) -> Optional[Dict[str, Any]]:
        provider = self._get_provider()
        return await provider.get_stock_basic_info(symbol=symbol)

    async def get_daily_quotes(
        self, symbol: str, start_date: str, end_date: str
    ) -> Optional[pd.DataFrame]:
        provider = self._get_provider()
        return await provider.get_historical_data(
            symbol=symbol, start_date=start_date, end_date=end_date
        )

    async def get_realtime_quotes(self) -> Optional[Dict[str, Dict[str, Any]]]:
        provider = self._get_provider()
        return await provider.get_realtime_quotes_batch()

    async def get_financial_data(self, symbol: str) -> Optional[pd.DataFrame]:
        provider = self._get_provider()
        return await provider.get_financial_data(symbol=symbol)

    async def get_daily_basic(self, trade_date: str) -> Optional[pd.DataFrame]:
        provider = self._get_provider()
        return await provider.get_daily_basic(trade_date=trade_date)

    async def get_news(
        self, symbol: str, days: int = 2, limit: int = 50
    ) -> Optional[List[Dict[str, Any]]]:
        provider = self._get_provider()
        return await provider.get_stock_news(symbol=symbol, limit=limit)
