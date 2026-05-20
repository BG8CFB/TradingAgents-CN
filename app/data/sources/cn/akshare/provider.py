"""
AKShare 数据源 Provider

独立 API 调用层，通过 api/ 子模块直接调用 AKShare SDK。
不再委托旧版 providers/china/akshare.py。
"""

import logging
from typing import Any, Dict, List, Optional

import pandas as pd

from app.data.sources.base.provider import BaseProvider

logger = logging.getLogger(__name__)


class AKShareSourceProvider(BaseProvider):
    """AKShare 数据源 Provider — 调用 api/ 子模块"""

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

    # ── 股票列表 & 基础信息 ──

    async def get_stock_list(self, market: str = None) -> Optional[pd.DataFrame]:
        from .api.stock_basic import fetch_stock_list
        return await fetch_stock_list()

    async def get_stock_basic_info(self, symbol: str) -> Optional[Dict[str, Any]]:
        from .api.stock_basic import fetch_stock_basic_info
        return await fetch_stock_basic_info(symbol)

    # ── 行情数据 ──

    async def get_daily_quotes(
        self, symbol: str, start_date: str, end_date: str
    ) -> Optional[pd.DataFrame]:
        from .api.daily_quotes import fetch_daily_quotes
        return await fetch_daily_quotes(symbol, start_date, end_date)

    async def get_realtime_quotes(self) -> Optional[Dict[str, Dict[str, Any]]]:
        from .api.quotes_batch import fetch_batch_quotes
        # 获取全市场批量行情（不指定具体 codes 时返回全部）
        return await fetch_batch_quotes([])

    # ── 财务数据 ──

    async def get_financial_data(self, symbol: str) -> Optional[Any]:
        from .api.financial import fetch_financial_data
        return await fetch_financial_data(symbol)

    # ── 新闻 ──

    async def get_news(
        self, symbol: str, days: int = 2, limit: int = 50
    ) -> Optional[List[Dict[str, Any]]]:
        from .api.news import fetch_news
        return await fetch_news(symbol=symbol, limit=limit)
