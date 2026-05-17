"""
港股 AKShare Provider

包装现有 improved_hk 模块，复用全部 API 调用逻辑。
"""

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
            from app.data.providers.hk.improved_hk import get_hk_stock_data_akshare
            return True
        except ImportError:
            return False

    async def get_stock_basic_info(self, symbol: str) -> Optional[Dict[str, Any]]:
        from app.data.providers.hk.improved_hk import get_hk_stock_info_akshare
        return get_hk_stock_info_akshare(symbol)

    async def get_daily_quotes(
        self, symbol: str, start_date: str, end_date: str
    ) -> Optional[pd.DataFrame]:
        from app.data.providers.hk.improved_hk import get_hk_stock_data_akshare
        return get_hk_stock_data_akshare(symbol, start_date, end_date)
