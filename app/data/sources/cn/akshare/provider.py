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

    async def get_adj_factors(
        self, symbol: str, start_date: str, end_date: str, **kwargs
    ) -> Optional[pd.DataFrame]:
        from .api.adj_factors import fetch_adj_factors
        return await fetch_adj_factors(symbol, start_date, end_date)

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

    async def get_intraday_quotes(
        self, symbol: str, start_date: str, end_date: str, **kwargs
    ) -> Optional[pd.DataFrame]:
        from .api.intraday_quotes import fetch_intraday_quotes
        freq = kwargs.get("freq", "30")
        return await fetch_intraday_quotes(symbol, period=freq)

    async def get_money_flow(
        self, symbol: str, start_date: str, end_date: str, **kwargs
    ) -> Optional[pd.DataFrame]:
        from .api.money_flow import fetch_money_flow_by_symbol
        return await fetch_money_flow_by_symbol(symbol)

    async def get_margin_trading(
        self, symbol: str, start_date: str, end_date: str, **kwargs
    ) -> Optional[pd.DataFrame]:
        from .api.margin_trading import fetch_margin_trading
        return await fetch_margin_trading(symbol)

    async def get_dragon_tiger(
        self, symbol: str, start_date: str, end_date: str, **kwargs
    ) -> Optional[pd.DataFrame]:
        from .api.dragon_tiger import fetch_dragon_tiger
        sd = start_date.replace("-", "")
        ed = end_date.replace("-", "")
        return await fetch_dragon_tiger(sd, ed)

    async def get_block_trade(
        self, symbol: str, start_date: str, end_date: str, **kwargs
    ) -> Optional[pd.DataFrame]:
        from .api.block_trade import fetch_block_trade
        sd = start_date.replace("-", "")
        ed = end_date.replace("-", "")
        return await fetch_block_trade(sd, ed)
