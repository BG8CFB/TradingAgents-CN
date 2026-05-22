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
        """连接到数据源，返回是否成功。"""

    @abstractmethod
    def is_available(self) -> bool:
        """检查数据源是否可用（已连接且有凭据）。"""

    async def get_stock_list(self, **kwargs) -> Optional[pd.DataFrame]:
        """获取股票列表。"""
        return None

    async def get_trade_calendar(self, exchange: str, start_date: str, end_date: str, **kwargs) -> Optional[pd.DataFrame]:
        """获取交易日历。"""
        return None

    async def get_daily_quotes(self, symbol: str, start_date: str, end_date: str, **kwargs) -> Optional[pd.DataFrame]:
        """获取日线行情。"""
        return None

    async def get_daily_indicators(self, symbol: str, start_date: str, end_date: str, **kwargs) -> Optional[pd.DataFrame]:
        """获取每日指标。"""
        return None

    async def get_financial_data(self, symbol: str, start_date: str, end_date: str,
                                statement_type: str = "", **kwargs) -> Optional[pd.DataFrame]:
        """获取财务数据。"""
        return None

    async def get_adj_factors(self, symbol: str, start_date: str, end_date: str, **kwargs) -> Optional[pd.DataFrame]:
        """获取复权因子。"""
        return None

    async def get_corporate_actions(self, symbol: str, start_date: str, end_date: str, **kwargs) -> Optional[pd.DataFrame]:
        """获取公司行为。"""
        return None

    async def get_news(self, symbol: str, start_date: str, end_date: str, **kwargs) -> Optional[pd.DataFrame]:
        """获取新闻公告。"""
        return None

    async def get_market_quotes(self, symbols: Optional[List[str]] = None, **kwargs) -> Optional[pd.DataFrame]:
        """获取市场快照。"""
        return None
