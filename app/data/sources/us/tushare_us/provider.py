"""Tushare US Provider — 使用独立 TUSHARE_US_TOKEN，积分门槛 ≥ 120。

Token：独立读取 TUSHARE_US_TOKEN（回退到 TUSHARE_TOKEN），
与 A 股 / 港股的凭据与积分完全隔离。
仅覆盖主要美股 + 中概股，维护白名单。不支持公司行为和新闻。
"""

import asyncio
import logging

from app.utils.ds_key_utils import get_datasource_api_key

import pandas as pd

from app.data.sources.base.provider import BaseProvider
from app.data.sources.base.exceptions import TokenInvalidError, InsufficientCreditsError

logger = logging.getLogger(__name__)


class TushareUSProvider(BaseProvider):
    """Tushare 美股数据源 Provider。"""

    def __init__(self):
        super().__init__(name="tushare_us", market="US")
        self._api = None

    def _get_api(self):
        if self._api is not None:
            return self._api
        try:
            import tushare as ts

            token = get_datasource_api_key("tushare_us")
            if not token:
                return None
            ts.set_token(token)
            self._api = ts.pro_api()
            return self._api
        except Exception as e:
            logger.debug(f"Tushare US API 初始化失败: {e}")
            return None

    async def connect(self) -> bool:
        api = await asyncio.to_thread(self._get_api)
        if api is None:
            self.connected = False
            return False
        try:
            df = await asyncio.to_thread(lambda: api.us_basic(limit=1))
            if df is not None and not df.empty:
                self.connected = True
                return True
        except Exception as e:
            err_msg = str(e).lower()
            if "token" in err_msg:
                raise TokenInvalidError("tushare_us", "us_basic", "Token 无效")
            if "积分" in err_msg or "credit" in err_msg:
                raise InsufficientCreditsError(
                    "tushare_us", "us_basic", "积分不足(需≥120)"
                )
            logger.error(f"Tushare US 连接失败: {e}")
        self.connected = False
        return False

    def is_available(self) -> bool:
        return self.connected and self._get_api() is not None

    async def get_stock_list(self, **kwargs) -> pd.DataFrame:
        api = self._get_api()
        if not api:
            return None
        try:
            return await asyncio.to_thread(lambda: api.us_basic())
        except Exception as e:
            logger.error(f"Tushare US 股票列表失败: {e}")
            return None

    async def get_trade_calendar(
        self,
        exchange: str = "NYSE",
        start_date: str = "1970-01-01",
        end_date: str = "2099-12-31",
        **kwargs,
    ) -> pd.DataFrame:
        api = self._get_api()
        if not api:
            return None
        try:
            return await asyncio.to_thread(
                lambda: api.us_tradecal(
                    exchange=exchange,
                    start_date=start_date.replace("-", ""),
                    end_date=end_date.replace("-", ""),
                )
            )
        except Exception as e:
            logger.error(f"Tushare US 交易日历失败: {e}")
            return None

    async def get_daily_quotes(
        self, symbol: str, start_date: str, end_date: str, **kwargs
    ) -> pd.DataFrame:
        api = self._get_api()
        if not api:
            return None
        from app.data.sources.us.tushare_us.code_resolver import get_us_ts_code
        ts_code = await get_us_ts_code(symbol, api=api)
        try:
            return await asyncio.to_thread(
                lambda: api.us_daily(
                    ts_code=ts_code,
                    start_date=start_date.replace("-", ""),
                    end_date=end_date.replace("-", ""),
                )
            )
        except Exception as e:
            logger.error(f"Tushare US 行情失败 {symbol}: {e}")
            return None

    async def get_daily_indicators(
        self, symbol: str, start_date: str, end_date: str, **kwargs
    ) -> pd.DataFrame:
        api = self._get_api()
        if not api:
            return None
        from app.data.sources.us.tushare_us.code_resolver import get_us_ts_code
        ts_code = await get_us_ts_code(symbol, api=api)
        try:
            return await asyncio.to_thread(
                lambda: api.us_daily_adj(
                    ts_code=ts_code,
                    start_date=start_date.replace("-", ""),
                    end_date=end_date.replace("-", ""),
                )
            )
        except Exception as e:
            logger.debug(f"Tushare US 指标失败 {symbol}: {e}")
            return None

    async def get_adj_factors(
        self, symbol: str, start_date: str, end_date: str, **kwargs
    ) -> pd.DataFrame:
        api = self._get_api()
        if not api:
            return None
        from app.data.sources.us.tushare_us.code_resolver import get_us_ts_code
        ts_code = await get_us_ts_code(symbol, api=api)
        try:
            return await asyncio.to_thread(
                lambda: api.us_adjfactor(
                    ts_code=ts_code,
                    start_date=start_date.replace("-", ""),
                    end_date=end_date.replace("-", ""),
                )
            )
        except Exception as e:
            logger.debug(f"Tushare US 复权因子失败 {symbol}: {e}")
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
        from app.data.sources.us.tushare_us.code_resolver import get_us_ts_code
        ts_code = await get_us_ts_code(symbol, api=api)
        stmt = statement_type or "income"
        try:
            from app.data.sources.us.tushare_us.api.us_financials import (
                fetch_financial_data,
            )
            return await fetch_financial_data(
                api,
                ts_code,
                statement_type=stmt,
                start_date=start_date or None,
                end_date=end_date or None,
            )
        except Exception as e:
            logger.debug(f"Tushare US 财务失败 {symbol}: {e}")
            return None

    async def get_corporate_actions(
        self, symbol: str, start_date: str, end_date: str, **kwargs
    ) -> pd.DataFrame:
        raise NotImplementedError(f"{self.name} 不支持 get_corporate_actions")

    async def get_news(
        self, symbol: str, start_date: str, end_date: str, **kwargs
    ) -> pd.DataFrame:
        raise NotImplementedError(f"{self.name} 不支持 get_news")
