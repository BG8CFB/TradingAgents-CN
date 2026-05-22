"""BaoStock CN Provider — 调用 api/ 子模块获取原始数据。"""

import logging
from typing import Optional

import pandas as pd

from app.data.sources.base.provider import BaseProvider

logger = logging.getLogger(__name__)


class BaoStockCNProvider(BaseProvider):
    """BaoStock A 股数据源 Provider。"""

    def __init__(self):
        super().__init__(name="baostock", market="CN")

    async def connect(self) -> bool:
        try:
            from .api.connection import is_available
            if not is_available():
                return False
            self.connected = True
            return True
        except Exception as e:
            logger.error(f"BaoStock 连接失败: {e}")
            return False

    def is_available(self) -> bool:
        try:
            from .api.connection import is_available
            return is_available()
        except Exception:
            return False

    async def get_stock_list(self, **kwargs) -> Optional[pd.DataFrame]:
        from .api.stock_basic import fetch_stock_list
        return await fetch_stock_list()

    async def get_daily_quotes(
        self, symbol: str, start_date: str, end_date: str, **kwargs
    ) -> Optional[pd.DataFrame]:
        from .api.daily_quotes import fetch_daily_quotes
        return await fetch_daily_quotes(symbol, start_date, end_date)

    async def get_financial_data(
        self, symbol: str, start_date: str, end_date: str,
        statement_type: str = "", **kwargs
    ) -> Optional[pd.DataFrame]:
        from .api.financial import fetch_financial_data
        return await fetch_financial_data(symbol)
