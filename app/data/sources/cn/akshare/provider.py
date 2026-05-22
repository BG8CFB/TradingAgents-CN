"""AKShare CN Provider — 调用 api/ 子模块获取原始数据。"""

import logging
from typing import Optional

import pandas as pd

from app.data.sources.base.provider import BaseProvider

logger = logging.getLogger(__name__)


class AKShareCNProvider(BaseProvider):
    """AKShare A 股数据源 Provider。"""

    def __init__(self):
        super().__init__(name="akshare", market="CN")

    async def connect(self) -> bool:
        try:
            import akshare as ak  # noqa: F401
            self.connected = True
            return True
        except ImportError:
            self.connected = False
            return False

    def is_available(self) -> bool:
        try:
            import akshare as ak  # noqa: F401
            return True
        except ImportError:
            return False

    async def get_stock_list(self, **kwargs) -> Optional[pd.DataFrame]:
        from .api.stock_basic import fetch_stock_list
        return await fetch_stock_list()

    async def get_daily_quotes(
        self, symbol: str, start_date: str, end_date: str, **kwargs
    ) -> Optional[pd.DataFrame]:
        from .api.daily_quotes import fetch_daily_quotes
        return await fetch_daily_quotes(symbol, start_date, end_date)

    async def get_daily_indicators(
        self, symbol: str, start_date: str, end_date: str, **kwargs
    ) -> Optional[pd.DataFrame]:
        from .api.financial import fetch_financial_data
        return await fetch_financial_data(symbol)

    async def get_financial_data(
        self, symbol: str, start_date: str, end_date: str,
        statement_type: str = "", **kwargs
    ) -> Optional[pd.DataFrame]:
        from .api.financial import fetch_financial_data
        return await fetch_financial_data(symbol)

    async def get_news(
        self, symbol: str, start_date: str, end_date: str, **kwargs
    ) -> Optional[pd.DataFrame]:
        from .api.news import fetch_news
        result = await fetch_news(symbol=symbol, limit=50)
        if result and isinstance(result, list):
            return pd.DataFrame(result)
        return None

    async def get_market_quotes(
        self, symbols=None, **kwargs
    ) -> Optional[pd.DataFrame]:
        from .api.quotes_batch import fetch_batch_quotes
        return await fetch_batch_quotes([])
