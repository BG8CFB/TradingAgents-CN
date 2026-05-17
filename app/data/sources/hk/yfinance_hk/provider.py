"""
港股 yfinance Provider

包装现有 hk_stock 模块，复用全部 API 调用逻辑。
"""

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
            from app.data.providers.hk.hk_stock import get_hk_stock_data, get_hk_stock_info
            return True
        except ImportError:
            return False

    async def get_stock_basic_info(self, symbol: str) -> Optional[Dict[str, Any]]:
        from app.data.providers.hk.hk_stock import get_hk_stock_info
        return get_hk_stock_info(symbol)

    async def get_daily_quotes(
        self, symbol: str, start_date: str, end_date: str
    ) -> Optional[pd.DataFrame]:
        from app.data.providers.hk.hk_stock import get_hk_stock_data
        return get_hk_stock_data(symbol, start_date, end_date)
