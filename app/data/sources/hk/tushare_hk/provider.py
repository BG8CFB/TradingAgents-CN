"""Tushare HK Provider — 委托 api/ 子模块调用 Tushare 港股 API。

Token：独立读取 TUSHARE_HK_TOKEN（回退到 TUSHARE_TOKEN），
与 A 股 / 美股的凭据与积分完全隔离。
积分门槛 ≥ 2000。
覆盖: 基础信息 / 行情 / 复权 / 财务 / 南向持股。
不支持: 公司行为 / 新闻（必须由 AKShare HK 承担）。
"""

import asyncio
import logging

import pandas as pd

from app.data.sources.base.provider import BaseProvider
from app.data.sources.base.exceptions import (
    DataNotFoundError,
    DataSourceError,
    TokenInvalidError,
    InsufficientCreditsError,
)

logger = logging.getLogger(__name__)


class TushareHKProvider(BaseProvider):
    """Tushare 港股数据源 Provider。"""

    def __init__(self):
        super().__init__(name="tushare_hk", market="HK")
        self._api = None

    def _get_api(self):
        if self._api is not None:
            return self._api
        try:
            import tushare as ts
            from app.utils.ds_key_utils import get_datasource_api_key

            token = get_datasource_api_key("tushare_hk")
            if not token:
                return None
            ts.set_token(token)
            self._api = ts.pro_api()
            return self._api
        except Exception as e:
            logger.debug(f"Tushare HK API 初始化失败: {e}")
            return None

    async def connect(self) -> bool:
        api = await asyncio.to_thread(self._get_api)
        if api is None:
            self.connected = False
            return False
        try:
            # 试探查询
            df = await asyncio.to_thread(lambda: api.hk_basic(limit=1))
            if df is not None and not df.empty:
                self.connected = True
                return True
        except Exception as e:
            err_msg = str(e).lower()
            if "token" in err_msg:
                raise TokenInvalidError("tushare_hk", "hk_basic", "Token 无效")
            if "积分" in err_msg or "credit" in err_msg:
                raise InsufficientCreditsError(
                    "tushare_hk", "hk_basic", "积分不足(需≥2000)"
                )
            logger.error(f"Tushare HK 连接失败: {e}")
        self.connected = False
        return False

    def is_available(self) -> bool:
        return self.connected and self._get_api() is not None

    async def get_stock_list(self, **kwargs) -> pd.DataFrame:
        api = self._get_api()
        if not api:
            return None
        try:
            from app.data.sources.hk.tushare_hk.api.hk_basic import fetch_stock_list
            return await fetch_stock_list(api)
        except (DataNotFoundError, DataSourceError) as e:
            logger.debug(f"Tushare HK 股票列表失败: {e}")
            return None
        except Exception as e:
            logger.error(f"Tushare HK 股票列表失败: {e}")
            return None

    async def get_trade_calendar(
        self,
        exchange: str = "HKEX",
        start_date: str = "1970-01-01",
        end_date: str = "2099-12-31",
        **kwargs,
    ) -> pd.DataFrame:
        api = self._get_api()
        if not api:
            return None
        try:
            from app.data.sources.hk.tushare_hk.api.hk_tradecal import (
                fetch_trade_calendar,
            )
            return await fetch_trade_calendar(
                api, exchange=exchange, start_date=start_date, end_date=end_date
            )
        except (DataNotFoundError, DataSourceError) as e:
            logger.debug(f"Tushare HK 交易日历失败: {e}")
            return None
        except Exception as e:
            logger.error(f"Tushare HK 交易日历失败: {e}")
            return None

    async def get_daily_quotes(
        self, symbol: str, start_date: str, end_date: str, **kwargs
    ) -> pd.DataFrame:
        api = self._get_api()
        if not api:
            return None
        ts_code = self._to_hk_ts_code(symbol)
        try:
            from app.data.sources.hk.tushare_hk.api.hk_daily import fetch_daily_quotes
            return await fetch_daily_quotes(api, ts_code, start_date, end_date)
        except (DataNotFoundError, DataSourceError) as e:
            logger.debug(f"Tushare HK 行情失败 {symbol}: {e}")
            return None
        except Exception as e:
            logger.error(f"Tushare HK 行情失败 {symbol}: {e}")
            return None

    async def get_daily_indicators(
        self, symbol: str, start_date: str, end_date: str, **kwargs
    ) -> pd.DataFrame:
        api = self._get_api()
        if not api:
            return None
        ts_code = self._to_hk_ts_code(symbol)
        try:
            from app.data.sources.hk.tushare_hk.api.hk_daily_adj import (
                fetch_daily_adj,
            )
            return await fetch_daily_adj(api, ts_code, start_date, end_date)
        except (DataNotFoundError, DataSourceError) as e:
            logger.debug(f"Tushare HK 每日指标失败 {symbol}: {e}")
            return None
        except Exception as e:
            logger.error(f"Tushare HK 每日指标失败 {symbol}: {e}")
            return None

    async def get_adj_factors(
        self, symbol: str, start_date: str, end_date: str, **kwargs
    ) -> pd.DataFrame:
        api = self._get_api()
        if not api:
            return None
        ts_code = self._to_hk_ts_code(symbol)
        try:
            from app.data.sources.hk.tushare_hk.api.hk_adjfactor import (
                fetch_adj_factors,
            )
            return await fetch_adj_factors(api, ts_code, start_date, end_date)
        except (DataNotFoundError, DataSourceError) as e:
            logger.debug(f"Tushare HK 复权因子失败 {symbol}: {e}")
            return None
        except Exception as e:
            logger.error(f"Tushare HK 复权因子失败 {symbol}: {e}")
            return None

    async def get_financial_data(
        self,
        symbol: str,
        start_date: str,
        end_date: str,
        statement_type: str = "",
        **kwargs,
    ) -> pd.DataFrame:
        api = self._get_api()
        if not api:
            return None
        ts_code = self._to_hk_ts_code(symbol)
        stmt = statement_type or "income"
        try:
            from app.data.sources.hk.tushare_hk.api.hk_financials import (
                fetch_financial_data,
            )
            return await fetch_financial_data(
                api,
                ts_code,
                statement_type=stmt,
                start_date=start_date or None,
                end_date=end_date or None,
            )
        except (DataNotFoundError, DataSourceError) as e:
            logger.debug(f"Tushare HK 财务失败 {symbol}: {e}")
            return None
        except Exception as e:
            logger.error(f"Tushare HK 财务失败 {symbol}: {e}")
            return None

    async def get_news(
        self, symbol: str, start_date: str, end_date: str, **kwargs
    ) -> pd.DataFrame:
        raise NotImplementedError(f"{self.name} 不支持 get_news")

    async def get_corporate_actions(
        self, symbol: str, start_date: str, end_date: str, **kwargs
    ) -> pd.DataFrame:
        raise NotImplementedError(f"{self.name} 不支持 get_corporate_actions")

    async def get_market_quotes(self, symbols=None, **kwargs) -> pd.DataFrame:
        api = self._get_api()
        if not api:
            return None
        try:
            from app.data.sources.hk.tushare_hk.api.rt_hk_k import (
                fetch_realtime_quotes,
            )
            return await fetch_realtime_quotes(api)
        except (DataNotFoundError, DataSourceError) as e:
            logger.debug(f"Tushare HK 实时行情失败: {e}")
            return None
        except Exception as e:
            logger.debug(f"Tushare HK 实时行情失败: {e}")
            return None

    @staticmethod
    def _to_hk_ts_code(symbol: str) -> str:
        """标准 5 位代码 → Tushare HK ts_code (5位.HK)。"""
        code = str(symbol).replace(".HK", "").lstrip("0").zfill(5)
        return f"{code}.HK"
