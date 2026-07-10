"""AKShare CN Provider — 调用 api/ 子模块获取原始数据。"""

import logging

import pandas as pd

from app.data.sources.base.provider import BaseProvider

logger = logging.getLogger(__name__)


class AKShareCNProvider(BaseProvider):
    """AKShare A 股数据源 Provider。"""

    def __init__(self):
        super().__init__(name="akshare", market="CN")

    async def connect(self) -> bool:
        try:
            import akshare as ak  # noqa: F401
            self.connected = True
            return True
        except ImportError:
            self.connected = False
            return False

    def is_available(self) -> bool:
        try:
            import akshare as ak  # noqa: F401
            return True
        except ImportError:
            return False

    async def get_stock_list(self, **kwargs) -> pd.DataFrame:
        from .api.stock_basic import fetch_stock_list
        return await fetch_stock_list()

    async def get_daily_quotes(
        self, symbol: str, start_date: str, end_date: str, **kwargs
    ) -> pd.DataFrame:
        from .api.daily_quotes import fetch_daily_quotes
        return await fetch_daily_quotes(symbol, start_date, end_date)

    async def get_daily_indicators(
        self, symbol: str, start_date: str, end_date: str, **kwargs
    ) -> pd.DataFrame:
        from .api.daily_indicators import fetch_daily_indicators_by_symbol
        return await fetch_daily_indicators_by_symbol(symbol, start_date, end_date)

    async def get_adj_factors(
        self, symbol: str, start_date: str, end_date: str, **kwargs
    ) -> pd.DataFrame:
        from .api.adj_factors import fetch_adj_factors
        return await fetch_adj_factors(symbol, start_date, end_date)

    async def get_financial_data(
        self, symbol: str, start_date: str, end_date: str,
        statement_type: str = "", **kwargs
    ) -> pd.DataFrame:
        from .api.financial import fetch_financial_data
        return await fetch_financial_data(
            symbol,
            start_date=start_date or None,
            end_date=end_date or None,
        )

    async def get_news(
        self, symbol: str, start_date: str, end_date: str, **kwargs
    ) -> pd.DataFrame:
        from .api.news import fetch_news
        result = await fetch_news(symbol=symbol, limit=50)
        if result and isinstance(result, list):
            return pd.DataFrame(result)
        return None

    async def get_market_quotes(
        self, symbols=None, **kwargs
    ) -> pd.DataFrame:
        from .api.quotes_batch import fetch_batch_quotes
        return await fetch_batch_quotes([])

    async def get_intraday_quotes(
        self, symbol: str, start_date: str, end_date: str, **kwargs
    ) -> pd.DataFrame:
        from .api.intraday_quotes import fetch_intraday_quotes
        freq = kwargs.get("freq", "30")
        return await fetch_intraday_quotes(symbol, period=freq)

    async def get_money_flow(
        self, symbol: str, start_date: str, end_date: str, **kwargs
    ) -> pd.DataFrame:
        from .api.money_flow import fetch_money_flow_by_symbol
        return await fetch_money_flow_by_symbol(symbol)

    async def get_margin_trading(
        self, symbol: str, start_date: str, end_date: str, **kwargs
    ) -> pd.DataFrame:
        from .api.margin_trading import fetch_margin_trading
        return await fetch_margin_trading(symbol)

    async def get_dragon_tiger(
        self, symbol: str, start_date: str, end_date: str, **kwargs
    ) -> pd.DataFrame:
        from .api.dragon_tiger import fetch_dragon_tiger
        sd = start_date.replace("-", "")
        ed = end_date.replace("-", "")
        return await fetch_dragon_tiger(sd, ed)

    async def get_block_trade(
        self, symbol: str, start_date: str, end_date: str, **kwargs
    ) -> pd.DataFrame:
        from .api.block_trade import fetch_block_trade
        sd = start_date.replace("-", "")
        ed = end_date.replace("-", "")
        return await fetch_block_trade(sd, ed)

    async def get_trade_calendar(
        self, exchange: str = "SSE", start_date: str = "1970-01-01",
        end_date: str = "2099-12-31", **kwargs
    ) -> pd.DataFrame:
        from .api.trade_calendar import fetch_trade_calendar
        return await fetch_trade_calendar(exchange, start_date, end_date)

    async def get_sw_daily(
        self, ts_code=None, trade_date=None, start_date=None, end_date=None, **kwargs
    ) -> pd.DataFrame:
        from .api.sw_daily import fetch_sw_daily
        return await fetch_sw_daily(
            ts_code=ts_code, trade_date=trade_date,
            start_date=start_date, end_date=end_date,
        )

    async def get_limit_step(
        self, ts_code=None, trade_date=None, start_date=None, end_date=None, **kwargs
    ) -> pd.DataFrame:
        from .api.limit_step import fetch_limit_step
        return await fetch_limit_step(
            trade_date=trade_date, start_date=start_date, end_date=end_date,
        )

    async def get_dividend(self, ts_code=None, record_date=None, ex_date=None, **kwargs) -> pd.DataFrame:
        from .api.dividend import fetch_dividend
        return await fetch_dividend(ts_code=ts_code)

    async def get_dragon_tiger_inst(self, trade_date=None, start_date=None, end_date=None, **kwargs):
        raise NotImplementedError("AKShare 不支持 get_dragon_tiger_inst")

    async def get_margin_summary(self, trade_date=None, start_date=None, end_date=None, **kwargs):
        raise NotImplementedError("AKShare 不支持 get_margin_summary")

    async def get_stock_company(self, ts_code=None, exchange=None, **kwargs):
        raise NotImplementedError("AKShare 不支持 get_stock_company")

    async def get_northbound_flow(self, start_date=None, end_date=None, **kwargs) -> pd.DataFrame:
        from .api.northbound_flow import fetch_northbound_flow
        return await fetch_northbound_flow(start_date=start_date, end_date=end_date)

    async def get_northbound_holding(self, **kwargs):
        raise NotImplementedError("AKShare 不支持 get_northbound_holding")

    async def get_share_unlock(self, start_date=None, end_date=None, **kwargs) -> pd.DataFrame:
        from .api.share_unlock import fetch_share_unlock
        return await fetch_share_unlock(start_date=start_date, end_date=end_date)

    async def get_pledge_stat(self, **kwargs):
        raise NotImplementedError("AKShare 不支持 get_pledge_stat")

    async def get_pledge_detail(self, **kwargs):
        raise NotImplementedError("AKShare 不支持 get_pledge_detail")

    async def get_trading_status(self, **kwargs):
        raise NotImplementedError("AKShare 不支持 get_trading_status")

    async def get_price_limit(self, trade_date=None, start_date=None, end_date=None, **kwargs) -> pd.DataFrame:
        from .api.price_limit import fetch_price_limit
        return await fetch_price_limit(trade_date=trade_date)

    async def get_index_daily(
        self, symbol: str, start_date: str = None, end_date: str = None, **kwargs
    ) -> pd.DataFrame:
        from .api.index_daily import fetch_index_daily
        return await fetch_index_daily(
            symbol, start_date=start_date, end_date=end_date
        )

    async def get_index_basic(self, market=None, category=None, **kwargs) -> pd.DataFrame:
        from .api.index_basic import fetch_index_basic
        return await fetch_index_basic(market=market, category=category)

    async def get_index_dailybasic(
        self, ts_code, start_date: str = None, end_date: str = None, **kwargs
    ) -> pd.DataFrame:
        from .api.index_dailybasic import fetch_index_dailybasic
        return await fetch_index_dailybasic(
            ts_code, start_date=start_date, end_date=end_date
        )

    async def get_index_weight(
        self, index_code=None, trade_date=None, start_date=None, end_date=None, **kwargs
    ) -> pd.DataFrame:
        from .api.index_weight import fetch_index_weight
        code = index_code or kwargs.get("ts_code")
        return await fetch_index_weight(
            code, trade_date=trade_date, start_date=start_date, end_date=end_date
        )

    async def get_announcement(self, start_date=None, end_date=None, **kwargs) -> pd.DataFrame:
        from .api.announcement import fetch_announcement
        return await fetch_announcement(start_date=start_date, end_date=end_date)

    async def get_ths_daily(
        self, ts_code=None, trade_date=None, start_date=None, end_date=None, **kwargs
    ) -> pd.DataFrame:
        from .api.ths_daily import fetch_ths_daily
        # akshare 按板块名称查询，路由器全市场批量模式不提供板块名称 → 直接降级
        return await fetch_ths_daily(
            ts_code, start_date=start_date, end_date=end_date
        )

    async def get_forecast(
        self, ts_code=None, start_date=None, end_date=None, **kwargs
    ) -> pd.DataFrame:
        from .api.forecast import fetch_forecast
        return await fetch_forecast(
            ts_code=ts_code, start_date=start_date, end_date=end_date
        )

    async def get_express(
        self, ts_code=None, start_date=None, end_date=None, **kwargs
    ) -> pd.DataFrame:
        from .api.express import fetch_express
        return await fetch_express(
            ts_code=ts_code, start_date=start_date, end_date=end_date
        )

    async def get_moneyflow_ind_dc(
        self, trade_date=None, start_date=None, end_date=None, **kwargs
    ) -> pd.DataFrame:
        from .api.moneyflow_ind_dc import fetch_moneyflow_ind_dc
        return await fetch_moneyflow_ind_dc(
            trade_date=trade_date, start_date=start_date, end_date=end_date
        )

    async def get_index_global(
        self, ts_code, start_date=None, end_date=None, **kwargs
    ) -> pd.DataFrame:
        from .api.index_data import fetch_index_global

        return await fetch_index_global(
            ts_code, start_date=start_date, end_date=end_date
        )

    async def get_chip_perf(
        self, symbol: str = None, start_date: str = None, end_date: str = None, **kwargs
    ) -> pd.DataFrame:
        from .api.chip_distribution import fetch_chip_perf
        return await fetch_chip_perf(
            symbol,
            start_date=start_date or None,
            end_date=end_date or None,
        )

    async def get_chip_distribution(self, symbol: str = None, trade_date: str = None, **kwargs):
        # akshare 仅提供每日筹码及胜率序列，无单日筹码分布明细；复用 get_chip_perf
        from .api.chip_distribution import fetch_chip_perf
        td = trade_date.replace("-", "") if trade_date else None
        return await fetch_chip_perf(symbol, start_date=td, end_date=td)
