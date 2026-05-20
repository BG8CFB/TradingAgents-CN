"""
BaseAdapter: 数据源标准化转换基类

职责：将 Provider 返回的原始数据转换为 Schema 标准格式。
负责字段映射、单位转换、数据过滤（丢弃不需要的字段）。
"""

import logging
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

import pandas as pd

from app.data.schema.stock_basic_info import StockBasicInfoSchema
from app.data.schema.stock_daily_quotes import StockDailyQuoteSchema
from app.data.schema.stock_financial_data import FinancialDataSchema
from app.data.schema.stock_news import NewsSchema


class BaseAdapter(ABC):
    """数据源标准化转换基类"""

    def __init__(self, provider, market: str, source_name: str):
        """
        Args:
            provider: BaseProvider 实例
            market: "CN" / "HK" / "US"
            source_name: "tushare" / "akshare" 等
        """
        self.provider = provider
        self.market = market
        self.source_name = source_name
        self.logger = logging.getLogger(f"adapter.{market}.{source_name}")

    @staticmethod
    def _safe_float(value) -> Optional[float]:
        """安全转换为浮点数"""
        if value is None or value == "" or (isinstance(value, float) and pd.isna(value)):
            return None
        try:
            return float(value)
        except (ValueError, TypeError):
            return None

    # ── 基础信息适配 ──

    @abstractmethod
    def adapt_basic_info(self, row: Any) -> StockBasicInfoSchema:
        """将单行原始数据转换为 StockBasicInfoSchema"""
        pass

    def adapt_basic_info_batch(self, df: pd.DataFrame) -> List[StockBasicInfoSchema]:
        """批量转换基础信息（默认逐行调用）"""
        return [self.adapt_basic_info(row) for _, row in df.iterrows()]

    # ── 行情数据适配 ──

    @abstractmethod
    def adapt_daily_quote(self, row: Any) -> StockDailyQuoteSchema:
        """将单行原始数据转换为 StockDailyQuoteSchema"""
        pass

    def adapt_daily_quote_batch(self, df: pd.DataFrame) -> List[StockDailyQuoteSchema]:
        """批量转换行情数据（默认逐行调用）"""
        return [self.adapt_daily_quote(row) for _, row in df.iterrows()]

    # ── 财务数据适配（可选） ──

    def adapt_financial(self, row: Any) -> Optional[FinancialDataSchema]:
        """将单行原始数据转换为 FinancialDataSchema（可选实现）"""
        return None

    # ── 新闻数据适配（可选） ──

    def adapt_news(self, raw: Dict[str, Any]) -> Optional[NewsSchema]:
        """将单条原始新闻转换为 NewsSchema（可选实现）"""
        return None

    # ── 每日指标适配（可选） ──

    def adapt_daily_indicators(self, row: Any) -> Optional[Any]:
        """将单行原始数据转换为 DailyIndicatorsSchema（可选实现）"""
        return None

    def adapt_daily_indicators_batch(self, df: pd.DataFrame) -> list:
        """批量转换每日指标（默认逐行调用）"""
        results = []
        for _, row in df.iterrows():
            item = self.adapt_daily_indicators(row)
            if item is not None:
                results.append(item)
        return results

    # ── 复权因子适配（可选） ──

    def adapt_adj_factors(self, row: Any) -> Optional[Any]:
        """将单行原始数据转换为 AdjFactorsSchema（可选实现）"""
        return None

    def adapt_adj_factors_batch(self, df: pd.DataFrame) -> list:
        """批量转换复权因子（默认逐行调用）"""
        results = []
        for _, row in df.iterrows():
            item = self.adapt_adj_factors(row)
            if item is not None:
                results.append(item)
        return results

    # ── 交易日历适配（可选） ──

    def adapt_trade_calendar(self, row: Any) -> Optional[Any]:
        """将单行原始数据转换为 TradeCalendarSchema（可选实现）"""
        return None

    def adapt_trade_calendar_batch(self, df: pd.DataFrame) -> list:
        """批量转换交易日历（默认逐行调用）"""
        results = []
        for _, row in df.iterrows():
            item = self.adapt_trade_calendar(row)
            if item is not None:
                results.append(item)
        return results
