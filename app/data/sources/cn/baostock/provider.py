"""
BaoStock 数据源 Provider

独立 API 调用层，通过 api/ 子模块直接调用 BaoStock SDK。
不再委托旧版 providers/china/baostock.py。
"""

import logging
from typing import Any, Dict, Optional

import pandas as pd

from app.data.sources.base.provider import BaseProvider

logger = logging.getLogger(__name__)


class BaoStockSourceProvider(BaseProvider):
    """BaoStock 数据源 Provider — 调用 api/ 子模块"""

    def __init__(self):
        super().__init__(name="baostock", market="CN")

    async def connect(self) -> bool:
        try:
            from .api.connection import baostock_session, is_available
            if not is_available():
                return False
            async with baostock_session():
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

    async def get_stock_list(self, market: str = None) -> Optional[pd.DataFrame]:
        from .api.stock_basic import fetch_stock_list
        return await fetch_stock_list()

    async def get_stock_basic_info(self, symbol: str) -> Optional[Dict[str, Any]]:
        # BaoStock 没有单只股票详情查询，通过列表过滤
        from .api.stock_basic import fetch_stock_list
        df = await fetch_stock_list()
        if df is not None and not df.empty:
            code = str(symbol).zfill(6)
            matches = df[df["code"] == code]
            if not matches.empty:
                return matches.iloc[0].to_dict()
        return None

    async def get_daily_quotes(
        self, symbol: str, start_date: str, end_date: str
    ) -> Optional[pd.DataFrame]:
        from .api.daily_quotes import fetch_daily_quotes
        return await fetch_daily_quotes(symbol, start_date, end_date)

    async def get_financial_data(self, symbol: str) -> Optional[Any]:
        from .api.financial import fetch_financial_data
        return await fetch_financial_data(symbol)
