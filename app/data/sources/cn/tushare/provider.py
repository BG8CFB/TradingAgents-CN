"""
Tushare 数据源 Provider

独立 API 调用层，通过 api/ 子模块直接调用 Tushare SDK。
不再委托旧版 providers/china/tushare.py。
"""

import logging
from typing import Any, Dict, List, Optional

import pandas as pd

from app.data.sources.base.provider import BaseProvider

logger = logging.getLogger(__name__)


class TushareSourceProvider(BaseProvider):
    """Tushare 数据源 Provider — 调用 api/ 子模块"""

    def __init__(self):
        super().__init__(name="tushare", market="CN")
        self._conn = None

    def _get_conn(self):
        if self._conn is None:
            from .api.connection import get_tushare_api
            self._conn = get_tushare_api()
        return self._conn

    async def connect(self) -> bool:
        try:
            conn = self._get_conn()
            self.connected = await conn.connect()
            return self.connected
        except Exception as e:
            logger.error(f"Tushare 连接失败: {e}")
            self.connected = False
            return False

    def is_available(self) -> bool:
        try:
            return self._get_conn().is_available()
        except Exception:
            return False

    # ── 股票列表 & 基础信息 ──

    async def get_stock_list(self, market: str = None) -> Optional[pd.DataFrame]:
        from .api.stock_basic import fetch_stock_list
        return await fetch_stock_list(self._get_conn(), market=market)

    async def get_stock_basic_info(self, symbol: str) -> Optional[Dict[str, Any]]:
        from .api.stock_basic import fetch_stock_basic_info
        ts_code = self._to_ts_code(symbol)
        df = await fetch_stock_basic_info(self._get_conn(), ts_code)
        if df is not None and not df.empty:
            return df.iloc[0].to_dict()
        return None

    # ── 行情数据 ──

    async def get_daily_quotes(
        self, symbol: str, start_date: str, end_date: str
    ) -> Optional[pd.DataFrame]:
        from .api.daily_quotes import fetch_daily_quotes
        ts_code = self._to_ts_code(symbol)
        return await fetch_daily_quotes(self._get_conn(), ts_code, start_date, end_date)

    async def get_realtime_quotes(self) -> Optional[pd.DataFrame]:
        from .api.daily_quotes import fetch_realtime_batch
        return await fetch_realtime_batch(self._get_conn())

    # ── 每日指标 ──

    async def get_daily_basic(self, trade_date: str) -> Optional[pd.DataFrame]:
        from .api.daily_indicators import fetch_daily_indicators
        return await fetch_daily_indicators(self._get_conn(), trade_date)

    async def get_daily_indicators(
        self,
        trade_date: Optional[str] = None,
        symbol: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> Optional[pd.DataFrame]:
        from .api.daily_indicators import fetch_daily_indicators, fetch_daily_indicators_by_symbol
        if symbol:
            ts_code = self._to_ts_code(symbol)
            return await fetch_daily_indicators_by_symbol(
                self._get_conn(), ts_code, start_date, end_date
            )
        if trade_date:
            return await fetch_daily_indicators(self._get_conn(), trade_date)
        return None

    # ── 复权因子 ──

    async def get_adj_factors(
        self, symbol: str, start_date: Optional[str] = None, end_date: Optional[str] = None,
    ) -> Optional[pd.DataFrame]:
        from .api.adj_factors import fetch_adj_factors
        ts_code = self._to_ts_code(symbol)
        return await fetch_adj_factors(self._get_conn(), ts_code, start_date, end_date)

    # ── 财务数据 ──

    async def get_financial_data(self, symbol: str) -> Optional[Dict[str, Any]]:
        from .api.financial import fetch_financial_data
        ts_code = self._to_ts_code(symbol)
        return await fetch_financial_data(self._get_conn(), ts_code)

    # ── 新闻 ──

    async def get_news(
        self, symbol: str, days: int = 2, limit: int = 50
    ) -> Optional[List[Dict[str, Any]]]:
        from .api.news import fetch_news
        return await fetch_news(self._get_conn(), symbol=symbol, limit=limit, hours_back=days * 24)

    # ── 交易日历 ──

    async def get_trade_calendar(
        self, exchange: str = "SSE",
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> Optional[pd.DataFrame]:
        from .api.trade_calendar import fetch_trade_calendar
        return await fetch_trade_calendar(self._get_conn(), exchange, start_date, end_date)

    # ── 通用查询（兼容旧调用） ──

    async def query_api(self, api_name: str, **kwargs) -> Optional[pd.DataFrame]:
        """通用 Tushare API 查询（同步在线程中执行）"""
        import asyncio
        conn = self._get_conn()
        return await asyncio.to_thread(conn.query, api_name, **kwargs)

    # ── 工具方法 ──

    @staticmethod
    def _to_ts_code(symbol: str) -> str:
        code = str(symbol).zfill(6)
        if code.startswith(("60", "68", "90")):
            return f"{code}.SH"
        elif code.startswith(("0", "3", "20")):
            return f"{code}.SZ"
        elif code.startswith(("4", "8")):
            return f"{code}.BJ"
        return f"{code}.SZ"
