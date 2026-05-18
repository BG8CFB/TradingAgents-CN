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
            import importlib.util
            return importlib.util.find_spec("app.data.providers.hk.hk_stock") is not None
        except (ImportError, ValueError):
            return False

    async def get_stock_basic_info(self, symbol: str) -> Optional[Dict[str, Any]]:
        from app.data.providers.hk.hk_stock import get_hk_stock_info
        return get_hk_stock_info(symbol)

    async def get_daily_quotes(
        self, symbol: str, start_date: str, end_date: str
    ) -> Optional[pd.DataFrame]:
        """获取港股日线行情数据，直接返回 DataFrame（绕过 format_stock_data）"""
        try:
            from app.data.providers.hk.hk_stock import get_hk_stock_provider
            provider = get_hk_stock_provider()
            return provider.get_stock_data(symbol, start_date, end_date)
        except Exception as e:
            logger.error(f"❌ [YFinance-HK] 获取行情失败: {symbol} - {e}")
            return None
