"""BaseProvider: 数据源原始 API 调用基类。

职责：纯粹的数据获取，返回原始格式（DataFrame / Dict）。
不感知 Schema、不做字段映射、不做单位转换、不写数据库。
"""

import logging
from abc import ABC, abstractmethod
from typing import List, Optional

import pandas as pd


class BaseProvider(ABC):
    """数据源原始 API 调用基类。"""

    def __init__(self, name: str, market: str):
        self.name = name
        self.market = market
        self.connected = False
        self.logger = logging.getLogger(f"sources.{market}.{name}")

    @abstractmethod
    async def connect(self) -> bool:
        """连接到数据源，返回是否成功。

        Raises:
            TokenInvalidError: 凭据无效（如 Tushare Token 非法）。
            InsufficientCreditsError: 数据源积分/配额不足。
        """

    @abstractmethod
    def is_available(self) -> bool:
        """检查数据源是否可用（已连接且有凭据）。"""

    async def get_stock_list(self, **kwargs) -> pd.DataFrame:
        """获取股票列表。

        Raises:
            NetworkError / DataFormatError / DataNotFoundError / DataSourceUnavailableError
        """
        raise NotImplementedError(f"{self.name} 不支持 get_stock_list")

    async def get_trade_calendar(self, exchange: str, start_date: str, end_date: str, **kwargs) -> pd.DataFrame:
        """获取交易日历。

        Raises:
            NetworkError / DataFormatError / DataNotFoundError / DataSourceUnavailableError
        """
        raise NotImplementedError(f"{self.name} 不支持 get_trade_calendar")

    async def get_daily_quotes(self, symbol: str, start_date: str, end_date: str, **kwargs) -> pd.DataFrame:
        """获取日线行情。

        Raises:
            NetworkError / DataFormatError / DataNotFoundError / DataSourceUnavailableError
        """
        raise NotImplementedError(f"{self.name} 不支持 get_daily_quotes")

    async def get_daily_indicators(self, symbol: str, start_date: str, end_date: str, **kwargs) -> pd.DataFrame:
        """获取每日指标（per-symbol 模式）。

        Raises:
            NetworkError / DataFormatError / DataNotFoundError / DataSourceUnavailableError
        """
        raise NotImplementedError(f"{self.name} 不支持 get_daily_indicators")

    async def get_daily_indicators_batch(self, trade_date: str, **kwargs) -> pd.DataFrame:
        """获取每日指标（按日期批量模式，一次获取全市场）。

        Raises:
            NetworkError / DataFormatError / DataNotFoundError / DataSourceUnavailableError
        """
        raise NotImplementedError(f"{self.name} 不支持 get_daily_indicators_batch")

    async def get_financial_data(self, symbol: str, start_date: str, end_date: str,
                                statement_type: str = "", **kwargs) -> pd.DataFrame:
        """获取财务数据。

        Raises:
            NetworkError / DataFormatError / DataNotFoundError / DataSourceUnavailableError
        """
        raise NotImplementedError(f"{self.name} 不支持 get_financial_data")

    async def get_adj_factors(self, symbol: str, start_date: str, end_date: str, **kwargs) -> pd.DataFrame:
        """获取复权因子。

        Raises:
            NetworkError / DataFormatError / DataNotFoundError / DataSourceUnavailableError
        """
        raise NotImplementedError(f"{self.name} 不支持 get_adj_factors")

    async def get_corporate_actions(self, symbol: str, start_date: str, end_date: str, **kwargs) -> pd.DataFrame:
        """获取公司行为。

        Raises:
            NetworkError / DataFormatError / DataNotFoundError / DataSourceUnavailableError
        """
        raise NotImplementedError(f"{self.name} 不支持 get_corporate_actions")

    async def get_news(self, symbol: str, start_date: str, end_date: str, **kwargs) -> pd.DataFrame:
        """获取新闻公告。

        Raises:
            NetworkError / DataFormatError / DataNotFoundError / DataSourceUnavailableError
        """
        raise NotImplementedError(f"{self.name} 不支持 get_news")

    async def get_market_quotes(self, symbols: Optional[List[str]] = None, **kwargs) -> pd.DataFrame:
        """获取市场快照。

        Raises:
            NetworkError / DataFormatError / DataNotFoundError / DataSourceUnavailableError
        """
        raise NotImplementedError(f"{self.name} 不支持 get_market_quotes")

    async def get_intraday_quotes(self, symbol: str, start_date: str, end_date: str, **kwargs) -> pd.DataFrame:
        """获取分钟线行情。

        Raises:
            NetworkError / DataFormatError / DataNotFoundError / DataSourceUnavailableError
        """
        raise NotImplementedError(f"{self.name} 不支持 get_intraday_quotes")

    async def get_money_flow(self, symbol: str, start_date: str, end_date: str, **kwargs) -> pd.DataFrame:
        """获取资金流向。

        Raises:
            NetworkError / DataFormatError / DataNotFoundError / DataSourceUnavailableError
        """
        raise NotImplementedError(f"{self.name} 不支持 get_money_flow")

    async def get_margin_trading(self, symbol: str, start_date: str, end_date: str, **kwargs) -> pd.DataFrame:
        """获取融资融券明细。

        Raises:
            NetworkError / DataFormatError / DataNotFoundError / DataSourceUnavailableError
        """
        raise NotImplementedError(f"{self.name} 不支持 get_margin_trading")

    async def get_dragon_tiger(self, symbol: str, start_date: str, end_date: str, **kwargs) -> pd.DataFrame:
        """获取龙虎榜数据。

        Raises:
            NetworkError / DataFormatError / DataNotFoundError / DataSourceUnavailableError
        """
        raise NotImplementedError(f"{self.name} 不支持 get_dragon_tiger")

    async def get_block_trade(self, symbol: str, start_date: str, end_date: str, **kwargs) -> pd.DataFrame:
        """获取大宗交易。

        Raises:
            NetworkError / DataFormatError / DataNotFoundError / DataSourceUnavailableError
        """
        raise NotImplementedError(f"{self.name} 不支持 get_block_trade")
