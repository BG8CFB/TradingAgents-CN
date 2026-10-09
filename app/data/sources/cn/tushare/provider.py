"""Tushare CN Provider — 调用 api/ 子模块获取原始数据。"""

import logging

import pandas as pd

from app.data.sources.base.provider import BaseProvider

logger = logging.getLogger(__name__)


class TushareCNProvider(BaseProvider):
    """Tushare A 股数据源 Provider。"""

    def __init__(self):
        super().__init__(name="tushare", market="CN")
        self._conn = None

    def _get_conn(self):
        if self._conn is None:
            from .api.connection import get_tushare_api

            self._conn = get_tushare_api()
        return self._conn

    async def connect(self) -> bool:
        try:
            conn = self._get_conn()
            self.connected = await conn.connect()
            return self.connected
        except Exception as e:
            logger.error(f"Tushare 连接失败: {e}")
            self.connected = False
            return False

    def is_available(self) -> bool:
        try:
            return self._get_conn().is_available()
        except Exception as e:
            logger.debug(f"Tushare可用性检查失败: {e}")
            return False

    async def get_stock_list(self, **kwargs) -> pd.DataFrame:
        from .api.stock_basic import fetch_stock_list

        # market=CN 显式传递：fetch_stock_list 依赖它决定是否追加北交所列表
        return await fetch_stock_list(self._get_conn(), market=kwargs.get("market", "CN"))

    async def get_trade_calendar(
        self,
        exchange: str = "SSE",
        start_date: str = "1970-01-01",
        end_date: str = "2099-12-31",
        **kwargs,
    ) -> pd.DataFrame:
        from .api.trade_calendar import fetch_trade_calendar

        return await fetch_trade_calendar(
            self._get_conn(), exchange, start_date, end_date
        )

    async def get_daily_quotes(
        self, symbol: str, start_date: str, end_date: str, **kwargs
    ) -> pd.DataFrame:
        from .api.daily_quotes import fetch_daily_quotes

        ts_code = self._to_ts_code(symbol)
        return await fetch_daily_quotes(self._get_conn(), ts_code, start_date, end_date)

    async def get_daily_quotes_batch(
        self, trade_date: str, **kwargs
    ) -> pd.DataFrame:
        from .api.daily_quotes import fetch_daily_quotes_batch

        return await fetch_daily_quotes_batch(self._get_conn(), trade_date)

    async def get_daily_indicators(
        self, symbol: str, start_date: str, end_date: str, **kwargs
    ) -> pd.DataFrame:
        from .api.daily_indicators import fetch_daily_indicators_by_symbol

        ts_code = self._to_ts_code(symbol)
        return await fetch_daily_indicators_by_symbol(
            self._get_conn(), ts_code, start_date, end_date
        )

    async def get_daily_indicators_batch(
        self, trade_date: str, **kwargs
    ) -> pd.DataFrame:
        from .api.daily_indicators import fetch_daily_indicators

        return await fetch_daily_indicators(self._get_conn(), trade_date)

    async def get_financial_data(
        self,
        symbol: str,
        start_date: str,
        end_date: str,
        statement_type: str = "",
        **kwargs,
    ) -> pd.DataFrame:
        from .api.financial import fetch_financial_data

        ts_code = self._to_ts_code(symbol)
        result = await fetch_financial_data(
            self._get_conn(),
            ts_code,
            start_date=start_date or None,
            end_date=end_date or None,
        )
        if result is None:
            return None
        if isinstance(result, dict):
            return pd.DataFrame([result])
        return result

    async def get_financial_data_batch(self, **kwargs) -> pd.DataFrame:
        from app.data.sources.cn.reporting import recent_report_periods
        from .api.financial import fetch_financial_data_batch

        return await fetch_financial_data_batch(
            self._get_conn(), recent_report_periods(5)
        )

    async def get_adj_factors(
        self, symbol: str, start_date: str, end_date: str, **kwargs
    ) -> pd.DataFrame:
        from .api.adj_factors import fetch_adj_factors

        ts_code = self._to_ts_code(symbol)
        return await fetch_adj_factors(self._get_conn(), ts_code, start_date, end_date)

    async def get_news(
        self, symbol: str, start_date: str, end_date: str, **kwargs
    ) -> pd.DataFrame:
        from .api.news import fetch_news

        result = await fetch_news(
            self._get_conn(),
            symbol=symbol,
            limit=50,
            start_date=start_date or None,
            end_date=end_date or None,
        )
        if result and isinstance(result, list):
            return pd.DataFrame(result)
        return None

    async def get_market_quotes(self, symbols=None, **kwargs) -> pd.DataFrame:
        from .api.daily_quotes import fetch_realtime_batch

        return await fetch_realtime_batch(self._get_conn())

    async def get_money_flow(
        self, symbol: str, start_date: str = None, end_date: str = None, **kwargs
    ) -> pd.DataFrame:
        from .api.money_flow import fetch_money_flow

        ts_code = self._to_ts_code(symbol)
        return await fetch_money_flow(self._get_conn(), ts_code, start_date, end_date)

    async def get_money_flow_batch(self, trade_date: str, **kwargs) -> pd.DataFrame:
        from .api.money_flow import fetch_money_flow_by_date

        return await fetch_money_flow_by_date(self._get_conn(), trade_date)

    async def get_margin_trading(
        self, symbol: str, start_date: str = None, end_date: str = None, **kwargs
    ) -> pd.DataFrame:
        from .api.margin_trading import fetch_margin_detail

        ts_code = self._to_ts_code(symbol)
        return await fetch_margin_detail(
            self._get_conn(), ts_code, start_date, end_date
        )

    async def get_dragon_tiger(
        self,
        symbol: str = None,
        trade_date: str = None,
        start_date: str = None,
        end_date: str = None,
        **kwargs,
    ) -> pd.DataFrame:
        from .api.dragon_tiger import fetch_dragon_tiger

        ts_code = self._to_ts_code(symbol) if symbol else None
        return await fetch_dragon_tiger(
            self._get_conn(),
            trade_date=trade_date,
            start_date=start_date,
            end_date=end_date,
            ts_code=ts_code,
        )

    async def get_block_trade(
        self, symbol: str = None, start_date: str = None, end_date: str = None, **kwargs
    ) -> pd.DataFrame:
        from .api.block_trade import fetch_block_trade

        ts_code = self._to_ts_code(symbol) if symbol else None
        return await fetch_block_trade(
            self._get_conn(), ts_code=ts_code, start_date=start_date, end_date=end_date
        )

    async def get_intraday_quotes(
        self,
        symbol: str,
        start_date: str = "",
        end_date: str = "",
        freq: str = "30min",
        **kwargs,
    ) -> pd.DataFrame:
        from .api.intraday_quotes import fetch_intraday_quotes

        ts_code = self._to_ts_code(symbol)
        return await fetch_intraday_quotes(self._get_conn(), ts_code, freq=freq)

    @staticmethod
    def _to_ts_code(symbol: str) -> str:
        code = str(symbol).zfill(6)
        # 沪市：60/68 股票、90 B股，以及 5 开头的基金/ETF（50/51/52/56/58…）
        # 注意：5 开头不可漏，否则 510xxx/588xxx 等沪市 ETF 会被误判为深市 → 取不到数
        if code.startswith(("60", "68", "90", "5")):
            return f"{code}.SH"
        elif code.startswith(("0", "3", "20")):
            return f"{code}.SZ"
        elif code.startswith(("4", "8", "92")):
            # 北交所：老代码 43x/83x/87x + 2024-11 起启用的 920 段。
            # 920xxx 落到 .SZ 会查询无数据，导致同步尾段三源全部失败。
            return f"{code}.BJ"
        return f"{code}.SZ"
