"""
Base classes and shared typing for data source adapters
"""
from abc import ABC, abstractmethod
from typing import List, Optional, Dict
import logging
import pandas as pd

logger = logging.getLogger(__name__)

# 默认 A 股数据源回退列表
_DEFAULT_CN_SOURCES = ["tushare", "akshare", "baostock"]


def get_enabled_cn_sources() -> List[str]:
    """从 MongoDB 读取启用的 A 股数据源优先级列表（同步版本）"""
    try:
        from app.core.database import get_mongo_db_sync
        db = get_mongo_db_sync()
        groupings = list(db.datasource_groupings.find(
            {"market_category_id": "a_shares", "enabled": True},
        ).sort("priority", -1))
        if groupings:
            sources = [
                g["data_source_name"].lower()
                for g in groupings
                if g.get("data_source_name")
            ]
            if sources:
                return sources
    except Exception as e:
        logger.debug(f"读取数据源优先级失败，使用默认值: {e}")
    return list(_DEFAULT_CN_SOURCES)


async def get_enabled_cn_sources_async() -> List[str]:
    """从 MongoDB 读取启用的 A 股数据源优先级列表（异步版本）"""
    try:
        from app.core.database import get_mongo_db
        db = get_mongo_db()
        groupings = await db.datasource_groupings.find(
            {"market_category_id": "a_shares", "enabled": True},
        ).sort("priority", -1).to_list(length=None)
        if groupings:
            sources = [
                g["data_source_name"].lower()
                for g in groupings
                if g.get("data_source_name")
            ]
            if sources:
                return sources
    except Exception as e:
        logger.debug(f"读取数据源优先级失败，使用默认值: {e}")
    return list(_DEFAULT_CN_SOURCES)


class DataSourceAdapter(ABC):
    """数据源适配器基类"""

    def __init__(self):
        self._priority: Optional[int] = None  # 动态优先级，从数据库加载

    @property
    @abstractmethod
    def name(self) -> str:
        """数据源名称"""
        raise NotImplementedError

    @property
    def priority(self) -> int:
        """数据源优先级（数字越小优先级越高）"""
        # 如果有动态设置的优先级，使用动态优先级；否则使用默认优先级
        if self._priority is not None:
            return self._priority
        return self._get_default_priority()

    @abstractmethod
    def _get_default_priority(self) -> int:
        """获取默认优先级（子类实现）"""
        raise NotImplementedError

    @abstractmethod
    def is_available(self) -> bool:
        """检查数据源是否可用"""
        raise NotImplementedError

    @abstractmethod
    def get_stock_list(self) -> Optional[pd.DataFrame]:
        """获取股票列表"""
        raise NotImplementedError

    @abstractmethod
    def get_daily_basic(self, trade_date: str) -> Optional[pd.DataFrame]:
        """获取每日基础财务数据"""
        raise NotImplementedError

    @abstractmethod
    def find_latest_trade_date(self) -> Optional[str]:
        """查找最新交易日期"""
        raise NotImplementedError

    # 新增：全市场实时快照（近实时价格/涨跌幅/成交额），键为6位代码
    @abstractmethod
    def get_realtime_quotes(self) -> Optional[Dict[str, Dict[str, Optional[float]]]]:
        """返回 { '000001': {'close': 10.0, 'pct_chg': 1.2, 'amount': 1.2e8}, ... }"""
        raise NotImplementedError

    # 新增：K线与新闻抽象接口
    @abstractmethod
    def get_kline(self, code: str, period: str = "day", limit: int = 120, adj: Optional[str] = None):
        """获取K线，返回按时间正序的列表: [{time, open, high, low, close, volume, amount}]"""
        raise NotImplementedError

    @abstractmethod
    def get_news(self, code: str, days: int = 2, limit: int = 50, include_announcements: bool = True):
        """获取新闻/公告，返回 [{title, source, time, url, type}]，type in ['news','announcement']"""
        raise NotImplementedError

    def query(self, api_name: str, **kwargs) -> Optional[pd.DataFrame]:
        """
        Generic query method for extended data types.
        Args:
            api_name: The name of the API/Interface (e.g. "fund_nav", "shibor").
            **kwargs: Parameters for the query.
        Returns:
            pd.DataFrame or None if not supported/failed.
        """
        return None
