"""
BaseProvider: 数据源原始 API 调用基类

职责：纯粹的数据获取，返回原始格式（DataFrame / Dict）。
不感知 Schema、不做字段映射、不做单位转换。
"""

import logging
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

import pandas as pd


class BaseProvider(ABC):
    """数据源原始 API 调用基类"""

    def __init__(self, name: str, market: str):
        self.name = name
        self.market = market
        self.connected = False
        self.logger = logging.getLogger(f"sources.{market}.{name}")

    @abstractmethod
    async def connect(self) -> bool:
        """连接到数据源"""
        pass

    @abstractmethod
    def is_available(self) -> bool:
        """检查数据源是否可用"""
        pass

    # ── 基础信息 ──

    async def get_stock_list(self) -> Optional[pd.DataFrame]:
        """获取股票列表（可选实现）"""
        return None

    async def get_stock_basic_info(self, symbol: str) -> Optional[Dict[str, Any]]:
        """获取单只股票基础信息（可选实现）"""
        return None

    # ── 行情数据 ──

    async def get_daily_quotes(
        self, symbol: str, start_date: str, end_date: str
    ) -> Optional[pd.DataFrame]:
        """
        获取日线行情数据

        Args:
            symbol: 股票代码
            start_date: YYYY-MM-DD
            end_date: YYYY-MM-DD

        Returns:
            原始 DataFrame（列名和数据源 API 返回一致）
        """
        return None

    async def get_realtime_quotes(self) -> Optional[Dict[str, Dict[str, Any]]]:
        """获取全市场实时行情（可选实现）"""
        return None

    # ── 财务数据 ──

    async def get_financial_data(self, symbol: str) -> Optional[pd.DataFrame]:
        """获取财务数据（可选实现）"""
        return None

    async def get_daily_basic(self, trade_date: str) -> Optional[pd.DataFrame]:
        """获取每日基础财务数据（可选实现）"""
        return None

    # ── 新闻数据 ──

    async def get_news(
        self, symbol: str, days: int = 2, limit: int = 50
    ) -> Optional[List[Dict[str, Any]]]:
        """获取新闻数据（可选实现）"""
        return None

    # ── 交易日历 ──

    async def get_trade_calendar(
        self, exchange: str = "SSE",
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> Optional[pd.DataFrame]:
        """获取交易日历（可选实现）"""
        return None

    # ── 每日指标 ──

    async def get_daily_indicators(
        self,
        trade_date: Optional[str] = None,
        symbol: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> Optional[pd.DataFrame]:
        """获取每日指标（PE/PB/市值等，可选实现）"""
        return None

    # ── 复权因子 ──

    async def get_adj_factors(
        self, symbol: str, start_date: Optional[str] = None, end_date: Optional[str] = None,
    ) -> Optional[pd.DataFrame]:
        """获取复权因子（可选实现）"""
        return None

    # ── K线 ──

    async def get_kline(
        self, symbol: str, period: str = "day", limit: int = 120
    ) -> Optional[List[Dict[str, Any]]]:
        """获取K线数据（可选实现）"""
        return None
