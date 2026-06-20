"""AKShare HK Provider — 委托 api/ 子模块调用 AKShare 港股 API。"""

import logging

import pandas as pd

from app.data.sources.base.provider import BaseProvider
from app.data.sources.base.exceptions import DataNotFoundError, DataSourceError

logger = logging.getLogger(__name__)


def _normalize_hk_symbol(symbol: str) -> str:
    """标准化港股代码为 5 位数字。"""
    return str(symbol).replace(".HK", "").lstrip("0").zfill(5)


class AKShareHKProvider(BaseProvider):
    """AKShare 港股数据源 Provider。"""

    def __init__(self):
        super().__init__(name="akshare_hk", market="HK")

    async def connect(self) -> bool:
        self.connected = True
        return True

    def is_available(self) -> bool:
        try:
            import akshare as ak  # noqa: F401
            return True
        except ImportError:
            return False

    async def get_stock_list(self, **kwargs) -> pd.DataFrame:
        try:
            from app.data.sources.hk.akshare_hk.api.basic_info import fetch_stock_list
            return await fetch_stock_list()
        except (DataNotFoundError, DataSourceError) as e:
            logger.debug(f"AKShare-HK 股票列表失败: {e}")
            return None
        except Exception as e:
            logger.error(f"AKShare-HK 股票列表失败: {e}")
            return None

    async def get_daily_quotes(
        self, symbol: str, start_date: str, end_date: str, **kwargs
    ) -> pd.DataFrame:
        try:
            from app.data.sources.hk.akshare_hk.api.daily_quotes import (
                fetch_daily_quotes,
            )
            return await fetch_daily_quotes(symbol, start_date, end_date)
        except (DataNotFoundError, DataSourceError) as e:
            logger.debug(f"AKShare-HK 行情失败 {symbol}: {e}")
            return None
        except Exception as e:
            logger.error(f"AKShare-HK 行情失败 {symbol}: {e}")
            return None

    async def get_corporate_actions(
        self, symbol: str, start_date: str, end_date: str, **kwargs
    ) -> pd.DataFrame:
        try:
            from app.data.sources.hk.akshare_hk.api.corporate_actions import (
                fetch_corporate_actions,
            )
            normalized = _normalize_hk_symbol(symbol)
            return await fetch_corporate_actions(normalized)
        except (DataNotFoundError, DataSourceError) as e:
            logger.debug(f"AKShare-HK 公司行为失败 {symbol}: {e}")
            return None
        except Exception as e:
            logger.debug(f"AKShare-HK 公司行为失败 {symbol}: {e}")
            return None

    async def get_news(
        self, symbol: str, start_date: str, end_date: str, **kwargs
    ) -> pd.DataFrame:
        # 市场级新闻（symbol=None）：复用 CN 的全球财经快讯（覆盖港股）
        if not symbol:
            from app.data.sources.cn.akshare.api.news import fetch_market_news
            result = await fetch_market_news(limit=100)
            return pd.DataFrame(result) if result else None
        try:
            from app.data.sources.hk.akshare_hk.api.news import fetch_news
            normalized = _normalize_hk_symbol(symbol)
            return await fetch_news(normalized)
        except (DataNotFoundError, DataSourceError) as e:
            logger.debug(f"AKShare-HK 新闻失败 {symbol}: {e}")
            return None
        except Exception as e:
            logger.debug(f"AKShare-HK 新闻失败 {symbol}: {e}")
            return None

    async def get_market_quotes(
        self, symbols=None, **kwargs
    ) -> pd.DataFrame:
        return await self.get_stock_list()
