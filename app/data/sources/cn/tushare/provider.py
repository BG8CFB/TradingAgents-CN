"""Tushare CN Provider — 调用 api/ 子模块获取原始数据。"""

import logging
from typing import Optional

import pandas as pd

from app.data.sources.base.provider import BaseProvider

logger = logging.getLogger(__name__)


class TushareCNProvider(BaseProvider):
    """Tushare A 股数据源 Provider。"""

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
        except Exception as e:
            logger.debug(f"Tushare可用性检查失败: {e}")
            return False

    async def get_stock_list(self, **kwargs) -> Optional[pd.DataFrame]:
        from .api.stock_basic import fetch_stock_list
        return await fetch_stock_list(self._get_conn())

    async def get_trade_calendar(
        self, exchange: str = "SSE", start_date: str = "1970-01-01",
        end_date: str = "2099-12-31", **kwargs
    ) -> Optional[pd.DataFrame]:
        from .api.trade_calendar import fetch_trade_calendar
        return await fetch_trade_calendar(self._get_conn(), exchange, start_date, end_date)

    async def get_daily_quotes(
        self, symbol: str, start_date: str, end_date: str, **kwargs
    ) -> Optional[pd.DataFrame]:
        from .api.daily_quotes import fetch_daily_quotes
        ts_code = self._to_ts_code(symbol)
        return await fetch_daily_quotes(self._get_conn(), ts_code, start_date, end_date)

    async def get_daily_indicators(
        self, symbol: str, start_date: str, end_date: str, **kwargs
    ) -> Optional[pd.DataFrame]:
        from .api.daily_indicators import fetch_daily_indicators_by_symbol
        ts_code = self._to_ts_code(symbol)
        return await fetch_daily_indicators_by_symbol(self._get_conn(), ts_code, start_date, end_date)

    async def get_daily_indicators_batch(self, trade_date: str, **kwargs) -> Optional[pd.DataFrame]:
        from .api.daily_indicators import fetch_daily_indicators
        return await fetch_daily_indicators(self._get_conn(), trade_date)

    async def get_financial_data(
        self, symbol: str, start_date: str, end_date: str,
        statement_type: str = "", **kwargs
    ) -> Optional[pd.DataFrame]:
        from .api.financial import fetch_financial_data
        ts_code = self._to_ts_code(symbol)
        result = await fetch_financial_data(self._get_conn(), ts_code)
        if result is None:
            return None
        if isinstance(result, dict):
            import pandas as pd
            return pd.DataFrame([result])
        return result

    async def get_adj_factors(
        self, symbol: str, start_date: str, end_date: str, **kwargs
    ) -> Optional[pd.DataFrame]:
        from .api.adj_factors import fetch_adj_factors
        ts_code = self._to_ts_code(symbol)
        return await fetch_adj_factors(self._get_conn(), ts_code, start_date, end_date)

    async def get_news(
        self, symbol: str, start_date: str, end_date: str, **kwargs
    ) -> Optional[pd.DataFrame]:
        from .api.news import fetch_news
        result = await fetch_news(self._get_conn(), symbol=symbol, limit=50)
        if result and isinstance(result, list):
            return pd.DataFrame(result)
        return None

    async def get_market_quotes(
        self, symbols=None, **kwargs
    ) -> Optional[pd.DataFrame]:
        from .api.daily_quotes import fetch_realtime_batch
        return await fetch_realtime_batch(self._get_conn())

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
