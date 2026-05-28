"""Tushare HK Provider — 调用 Tushare 港股 API。

独立 Token (TUSHARE_HK_TOKEN)，积分门槛 ≥ 2000。
覆盖: 基础信息 / 行情 / 复权 / 财务 / 南向持股。
不支持: 公司行为 / 新闻（必须由 AKShare HK 承担）。
"""

import asyncio
import logging
from typing import Optional

import pandas as pd

from app.data.sources.base.provider import BaseProvider
from app.data.sources.base.exceptions import TokenInvalidError, InsufficientCreditsError

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
            token = get_datasource_api_key("tushare")
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
                raise InsufficientCreditsError("tushare_hk", "hk_basic", "积分不足(需≥2000)")
            logger.error(f"Tushare HK 连接失败: {e}")
        self.connected = False
        return False

    def is_available(self) -> bool:
        return self.connected and self._get_api() is not None

    async def get_stock_list(self, **kwargs) -> Optional[pd.DataFrame]:
        api = self._get_api()
        if not api:
            return None
        try:
            return await asyncio.to_thread(lambda: api.hk_basic())
        except Exception as e:
            logger.error(f"Tushare HK 股票列表失败: {e}")
            return None

    async def get_trade_calendar(
        self, exchange: str = "HKEX", start_date: str = "1970-01-01",
        end_date: str = "2099-12-31", **kwargs
    ) -> Optional[pd.DataFrame]:
        api = self._get_api()
        if not api:
            return None
        try:
            return await asyncio.to_thread(
                lambda: api.hk_tradecal(exchange=exchange, start_date=start_date, end_date=end_date)
            )
        except Exception as e:
            logger.error(f"Tushare HK 交易日历失败: {e}")
            return None

    async def get_daily_quotes(
        self, symbol: str, start_date: str, end_date: str, **kwargs
    ) -> Optional[pd.DataFrame]:
        api = self._get_api()
        if not api:
            return None
        ts_code = self._to_hk_ts_code(symbol)
        try:
            return await asyncio.to_thread(
                lambda: api.hk_daily(ts_code=ts_code, start_date=start_date.replace("-", ""),
                                     end_date=end_date.replace("-", ""))
            )
        except Exception as e:
            logger.error(f"Tushare HK 行情失败 {symbol}: {e}")
            return None

    async def get_daily_indicators(
        self, symbol: str, start_date: str, end_date: str, **kwargs
    ) -> Optional[pd.DataFrame]:
        api = self._get_api()
        if not api:
            return None
        ts_code = self._to_hk_ts_code(symbol)
        try:
            return await asyncio.to_thread(
                lambda: api.hk_daily_adj(ts_code=ts_code, start_date=start_date.replace("-", ""),
                                         end_date=end_date.replace("-", ""))
            )
        except Exception as e:
            logger.debug(f"Tushare HK 每日指标失败 {symbol}: {e}")
            return None

    async def get_adj_factors(
        self, symbol: str, start_date: str, end_date: str, **kwargs
    ) -> Optional[pd.DataFrame]:
        api = self._get_api()
        if not api:
            return None
        ts_code = self._to_hk_ts_code(symbol)
        try:
            return await asyncio.to_thread(
                lambda: api.hk_adjfactor(ts_code=ts_code, start_date=start_date.replace("-", ""),
                                         end_date=end_date.replace("-", ""))
            )
        except Exception as e:
            logger.debug(f"Tushare HK 复权因子失败 {symbol}: {e}")
            return None

    async def get_financial_data(
        self, symbol: str, start_date: str, end_date: str,
        statement_type: str = "", **kwargs
    ) -> Optional[pd.DataFrame]:
        api = self._get_api()
        if not api:
            return None
        ts_code = self._to_hk_ts_code(symbol)
        try:
            if statement_type == "income" or not statement_type:
                return await asyncio.to_thread(lambda: api.hk_income(ts_code=ts_code))
            elif statement_type == "balance":
                return await asyncio.to_thread(lambda: api.hk_balancesheet(ts_code=ts_code))
            elif statement_type == "cashflow":
                return await asyncio.to_thread(lambda: api.hk_cashflow(ts_code=ts_code))
            elif statement_type == "indicator":
                return await asyncio.to_thread(lambda: api.hk_fina_indicator(ts_code=ts_code))
            else:
                return await asyncio.to_thread(lambda: api.hk_income(ts_code=ts_code))
        except Exception as e:
            logger.debug(f"Tushare HK 财务失败 {symbol}: {e}")
            return None

    async def get_news(
        self, symbol: str, start_date: str, end_date: str, **kwargs
    ) -> Optional[pd.DataFrame]:
        return None  # Tushare HK 不支持新闻

    async def get_corporate_actions(
        self, symbol: str, start_date: str, end_date: str, **kwargs
    ) -> Optional[pd.DataFrame]:
        return None  # Tushare HK 不支持公司行为

    async def get_market_quotes(
        self, symbols=None, **kwargs
    ) -> Optional[pd.DataFrame]:
        api = self._get_api()
        if not api:
            return None
        try:
            return await asyncio.to_thread(lambda: api.rt_hk_k())
        except Exception as e:
            logger.debug(f"Tushare HK 实时行情失败: {e}")
            return None

    @staticmethod
    def _to_hk_ts_code(symbol: str) -> str:
        """标准 5 位代码 → Tushare HK ts_code (5位.HK)。"""
        code = str(symbol).replace(".HK", "").lstrip("0").zfill(5)
        return f"{code}.HK"
