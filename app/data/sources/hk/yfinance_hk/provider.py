"""yfinance HK Provider — 委托 api/ 子模块调用 yfinance 港股 API。"""

import logging

import pandas as pd

from app.data.sources.base.exceptions import DataNotFoundError, DataSourceError
from app.data.sources.base.provider import BaseProvider

logger = logging.getLogger(__name__)


class YFinanceHKProvider(BaseProvider):
    """yfinance 港股数据源 Provider。"""

    def __init__(self):
        super().__init__(name="yfinance_hk", market="HK")

    async def connect(self) -> bool:
        self.connected = True
        return True

    def is_available(self) -> bool:
        try:
            import yfinance as yf  # noqa: F401
            return True
        except ImportError:
            return False

    async def get_stock_list(self, **kwargs) -> pd.DataFrame:
        raise NotImplementedError(f"{self.name} 不支持 get_stock_list")

    async def get_daily_quotes(
        self, symbol: str, start_date: str, end_date: str, **kwargs
    ) -> pd.DataFrame:
        try:
            from app.data.sources.hk.yfinance_hk.api.daily_quotes import (
                fetch_daily_quotes,
            )
            return await fetch_daily_quotes(symbol, start_date, end_date)
        except (DataNotFoundError, DataSourceError) as e:
            logger.debug(f"yfinance-HK 行情失败 {symbol}: {e}")
            return None
        except Exception as e:
            logger.error(f"yfinance-HK 行情失败 {symbol}: {e}")
            return None

    async def get_corporate_actions(
        self, symbol: str, start_date: str, end_date: str, **kwargs
    ) -> pd.DataFrame:
        try:
            from app.data.sources.hk.yfinance_hk.api.corporate_actions import (
                fetch_corporate_actions,
            )
            return await fetch_corporate_actions(symbol, start_date, end_date)
        except (DataNotFoundError, DataSourceError) as e:
            logger.debug(f"yfinance-HK 公司行为失败 {symbol}: {e}")
            return None
        except Exception as e:
            logger.debug(f"yfinance-HK 公司行为失败 {symbol}: {e}")
            return None

    async def get_financial_data(
        self, symbol: str, start_date: str, end_date: str,
        statement_type: str = "", **kwargs
    ) -> pd.DataFrame:
        try:
            from app.data.sources.hk.yfinance_hk.api.financial_data import (
                fetch_financial_data,
            )
            return await fetch_financial_data(
                symbol,
                statement_type=statement_type or "income",
                start_date=start_date or None,
                end_date=end_date or None,
            )
        except (DataNotFoundError, DataSourceError) as e:
            logger.debug(f"yfinance-HK 财务数据失败 {symbol}: {e}")
            return None
        except Exception as e:
            logger.debug(f"yfinance-HK 财务数据失败 {symbol}: {e}")
            return None
