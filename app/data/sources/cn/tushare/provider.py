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
        return await fetch_stock_list(self._get_conn(), market=kwargs.get("market"))

    async def get_trade_calendar(
        self, exchange: str = "SSE", start_date: str = "1970-01-01",
        end_date: str = "2099-12-31", **kwargs
    ) -> pd.DataFrame:
        from .api.trade_calendar import fetch_trade_calendar
        return await fetch_trade_calendar(self._get_conn(), exchange, start_date, end_date)

    async def get_daily_quotes(
        self, symbol: str, start_date: str, end_date: str, **kwargs
    ) -> pd.DataFrame:
        from .api.daily_quotes import fetch_daily_quotes
        ts_code = self._to_ts_code(symbol)
        return await fetch_daily_quotes(self._get_conn(), ts_code, start_date, end_date)

    async def get_daily_indicators(
        self, symbol: str, start_date: str, end_date: str, **kwargs
    ) -> pd.DataFrame:
        from .api.daily_indicators import fetch_daily_indicators_by_symbol
        ts_code = self._to_ts_code(symbol)
        return await fetch_daily_indicators_by_symbol(self._get_conn(), ts_code, start_date, end_date)

    async def get_daily_indicators_batch(self, trade_date: str, **kwargs) -> pd.DataFrame:
        from .api.daily_indicators import fetch_daily_indicators
        return await fetch_daily_indicators(self._get_conn(), trade_date)

    async def get_daily_quotes_batch(self, trade_date: str, **kwargs) -> pd.DataFrame:
        from .api.daily_quotes import fetch_daily_quotes_by_date
        return await fetch_daily_quotes_by_date(self._get_conn(), trade_date)

    async def get_adj_factors_batch(self, trade_date: str, **kwargs) -> pd.DataFrame:
        from .api.adj_factors import fetch_adj_factors_by_date
        return await fetch_adj_factors_by_date(self._get_conn(), trade_date)

    async def get_money_flow_batch(self, trade_date: str, **kwargs) -> pd.DataFrame:
        from .api.money_flow import fetch_money_flow_by_date
        return await fetch_money_flow_by_date(self._get_conn(), trade_date)

    async def get_financial_data(
        self, symbol: str, start_date: str, end_date: str,
        statement_type: str = "", **kwargs
    ) -> pd.DataFrame:
        from .api.financial import fetch_financial_data
        ts_code = self._to_ts_code(symbol)
        result = await fetch_financial_data(
            self._get_conn(), ts_code,
            start_date=start_date or None,
            end_date=end_date or None,
        )
        if result is None:
            return None
        if isinstance(result, dict):
            # 从 raw_data 中提取多个报告期的数据
            raw_data = result.get("raw_data", {})
            if raw_data:
                income_stmts = raw_data.get("income_statement", [])
                balance_stmts = raw_data.get("balance_sheet", [])
                cashflow_stmts = raw_data.get("cashflow_statement", [])
                indicator_stmts = raw_data.get("financial_indicators", [])

                if income_stmts:
                    # 构建包含多个报告期的 DataFrame，去重
                    records = []
                    seen_periods = set()
                    for income in income_stmts:
                        end_date = income.get("end_date")
                        # 去重：同一报告期只保留一条记录
                        if end_date in seen_periods:
                            continue
                        seen_periods.add(end_date)

                        # 查找对应的 balance sheet、cashflow、indicator
                        balance = next((b for b in balance_stmts if b.get("end_date") == end_date), {})
                        cashflow = next((c for c in cashflow_stmts if c.get("end_date") == end_date), {})
                        indicator = next((i for i in indicator_stmts if i.get("end_date") == end_date), {})

                        record = {
                            "ts_code": ts_code,
                            "symbol": result.get("symbol"),
                            "end_date": end_date,
                            "ann_date": income.get("ann_date"),
                            "statement_type": "indicator",  # 综合财务指标
                            # 利润表
                            "revenue": income.get("revenue"),
                            "n_income": income.get("n_income"),
                            "n_income_attr_p": income.get("n_income_attr_p"),
                            "oper_cost": income.get("oper_cost"),
                            # 资产负债表
                            "total_assets": balance.get("total_assets"),
                            "total_liab": balance.get("total_liab"),
                            "total_hldr_eqy_exc_min_int": balance.get("total_hldr_eqy_exc_min_int"),
                            # 现金流量表
                            "n_cashflow_act": cashflow.get("n_cashflow_act"),
                            # 财务指标
                            "roe": indicator.get("roe"),
                            "roa": indicator.get("roa"),
                            "grossprofit_margin": indicator.get("grossprofit_margin"),
                            "netprofit_margin": indicator.get("netprofit_margin"),
                            "debt_to_assets": indicator.get("debt_to_assets"),
                            "current_ratio": indicator.get("current_ratio"),
                            "quick_ratio": indicator.get("quick_ratio"),
                            "eps": indicator.get("eps"),
                            "bps": indicator.get("bps"),
                        }
                        records.append(record)
                    return pd.DataFrame(records)
            # 如果 raw_data 为空或无法提取，返回标准化后的单一数据
            return pd.DataFrame([result])
        return result

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

    async def get_news_batch(self, start_date: str, end_date: str, **kwargs) -> pd.DataFrame:
        """按日期范围批量获取全市场新闻"""
        from .api.news import fetch_news_by_date
        return await fetch_news_by_date(
            self._get_conn(),
            start_date=start_date,
            end_date=end_date,
            limit=2000,
        )

    async def get_market_quotes(
        self, symbols=None, **kwargs
    ) -> pd.DataFrame:
        from .api.daily_quotes import fetch_realtime_batch
        return await fetch_realtime_batch(self._get_conn())

    async def get_money_flow(
        self, symbol: str, start_date: str = None, end_date: str = None, **kwargs
    ) -> pd.DataFrame:
        from .api.money_flow import fetch_money_flow
        ts_code = self._to_ts_code(symbol)
        return await fetch_money_flow(self._get_conn(), ts_code, start_date, end_date)

    async def get_margin_trading(
        self, symbol: str, start_date: str = None, end_date: str = None, **kwargs
    ) -> pd.DataFrame:
        from .api.margin_trading import fetch_margin_detail
        ts_code = self._to_ts_code(symbol)
        return await fetch_margin_detail(self._get_conn(), ts_code, start_date, end_date)

    async def get_dragon_tiger(
        self, symbol: str = None, trade_date: str = None,
        start_date: str = None, end_date: str = None, **kwargs
    ) -> pd.DataFrame:
        from .api.dragon_tiger import fetch_dragon_tiger
        ts_code = self._to_ts_code(symbol) if symbol and symbol != "__all__" else None
        return await fetch_dragon_tiger(
            self._get_conn(), trade_date=trade_date,
            start_date=start_date, end_date=end_date, ts_code=ts_code,
        )

    async def get_block_trade(
        self, symbol: str = None, start_date: str = None, end_date: str = None, **kwargs
    ) -> pd.DataFrame:
        from .api.block_trade import fetch_block_trade
        ts_code = self._to_ts_code(symbol) if symbol else None
        return await fetch_block_trade(self._get_conn(), ts_code=ts_code,
                                       start_date=start_date, end_date=end_date)

    async def get_dragon_tiger_inst(
        self, trade_date: str = None, start_date: str = None, end_date: str = None, **kwargs
    ) -> pd.DataFrame:
        """获取龙虎榜机构交易明细（top_inst）"""
        from .api.dragon_tiger import fetch_dragon_tiger_inst
        return await fetch_dragon_tiger_inst(
            self._get_conn(), trade_date=trade_date,
            start_date=start_date, end_date=end_date,
        )

    async def get_margin_summary(
        self, trade_date: str = None, start_date: str = None, end_date: str = None,
        exchange_id: str = None, **kwargs
    ) -> pd.DataFrame:
        """获取融资融券交易汇总（margin 接口）"""
        from .api.margin_trading import fetch_margin_summary
        return await fetch_margin_summary(
            self._get_conn(), trade_date=trade_date,
            start_date=start_date, end_date=end_date,
            exchange_id=exchange_id,
        )

    async def get_stock_company(
        self, ts_code: str = None, exchange: str = None, **kwargs
    ) -> pd.DataFrame:
        """获取上市公司基本信息（stock_company）"""
        from .api.stock_basic import fetch_stock_company
        return await fetch_stock_company(self._get_conn(), ts_code=ts_code, exchange=exchange)

    async def get_margin_trading_batch(self, symbols: list, start_date: str = None, end_date: str = None, **kwargs) -> pd.DataFrame:
        """批量获取融资融券（ts_code 分批，每批 50 个）"""
        from .api.margin_trading import fetch_margin_batch
        import asyncio
        conn = self._get_conn()
        chunk_size = 50
        all_dfs = []
        for i in range(0, len(symbols), chunk_size):
            chunk = [self._to_ts_code(s) for s in symbols[i:i + chunk_size]]
            df = await fetch_margin_batch(conn, chunk, start_date, end_date)
            if df is not None and not df.empty:
                all_dfs.append(df)
            if i + chunk_size < len(symbols):
                await asyncio.sleep(0.3)
        if all_dfs:
            return pd.concat(all_dfs, ignore_index=True)
        return pd.DataFrame()

    async def get_intraday_quotes(
        self, symbol: str, freq: str = "30min", **kwargs
    ) -> pd.DataFrame:
        from .api.intraday_quotes import fetch_intraday_quotes
        ts_code = self._to_ts_code(symbol)
        return await fetch_intraday_quotes(self._get_conn(), ts_code, freq=freq)

    # ========== B 类接口 ==========

    async def get_northbound_flow(self, trade_date=None, start_date=None, end_date=None, **kwargs):
        from .api.northbound_flow import fetch_northbound_flow
        return await fetch_northbound_flow(self._get_conn(), trade_date=trade_date, start_date=start_date, end_date=end_date)

    async def get_northbound_holding(self, ts_code=None, trade_date=None, start_date=None, end_date=None, **kwargs):
        from .api.northbound_holding import fetch_northbound_holding
        return await fetch_northbound_holding(self._get_conn(), ts_code=ts_code, trade_date=trade_date, start_date=start_date, end_date=end_date)

    async def get_share_unlock(self, ts_code=None, start_date=None, end_date=None, **kwargs):
        from .api.share_unlock import fetch_share_unlock
        return await fetch_share_unlock(self._get_conn(), ts_code=ts_code, start_date=start_date, end_date=end_date)

    async def get_pledge_stat(self, ts_code=None, end_date=None, **kwargs):
        from .api.pledge import fetch_pledge_stat
        return await fetch_pledge_stat(self._get_conn(), ts_code=ts_code, end_date=end_date)

    async def get_pledge_detail(self, ts_code=None, end_date=None, **kwargs):
        from .api.pledge import fetch_pledge_detail
        return await fetch_pledge_detail(self._get_conn(), ts_code=ts_code, end_date=end_date)

    async def get_trading_status(self, ts_code=None, trade_date=None, start_date=None, end_date=None, **kwargs):
        from .api.trading_status import fetch_suspend_info
        return await fetch_suspend_info(self._get_conn(), ts_code=ts_code, trade_date=trade_date, start_date=start_date, end_date=end_date)

    async def get_price_limit(self, ts_code=None, trade_date=None, **kwargs):
        from .api.price_limit import fetch_price_limit
        return await fetch_price_limit(self._get_conn(), ts_code=ts_code, trade_date=trade_date)

    async def get_index_daily(self, ts_code, start_date=None, end_date=None, **kwargs):
        from .api.index_data import fetch_index_daily
        return await fetch_index_daily(self._get_conn(), ts_code, start_date=start_date, end_date=end_date)

    async def get_index_weight(self, index_code=None, trade_date=None, start_date=None, end_date=None, **kwargs):
        from .api.index_data import fetch_index_weight
        return await fetch_index_weight(self._get_conn(), index_code=index_code, trade_date=trade_date, start_date=start_date, end_date=end_date)

    async def get_index_basic(self, market=None, category=None, **kwargs):
        from .api.index_data import fetch_index_basic
        return await fetch_index_basic(self._get_conn(), market=market, category=category)

    async def get_index_dailybasic(self, ts_code, start_date=None, end_date=None, **kwargs):
        from .api.index_data import fetch_index_dailybasic
        return await fetch_index_dailybasic(self._get_conn(), ts_code, start_date=start_date, end_date=end_date)

    async def get_index_global(self, ts_code, start_date=None, end_date=None, **kwargs):
        from .api.index_data import fetch_index_global
        return await fetch_index_global(self._get_conn(), ts_code, start_date=start_date, end_date=end_date)

    async def get_announcement(self, start_date=None, end_date=None, **kwargs):
        from .api.news import fetch_announcement
        return await fetch_announcement(self._get_conn(), start_date=start_date, end_date=end_date)

    async def get_chip_perf(self, symbol, trade_date=None, start_date=None, end_date=None, **kwargs):
        from .api.chip_distribution import fetch_chip_perf
        ts_code = self._to_ts_code(symbol)
        return await fetch_chip_perf(self._get_conn(), ts_code, trade_date=trade_date, start_date=start_date, end_date=end_date)

    async def get_chip_distribution(self, symbol, trade_date=None, **kwargs):
        from .api.chip_distribution import fetch_chip_distribution
        ts_code = self._to_ts_code(symbol)
        return await fetch_chip_distribution(self._get_conn(), ts_code, trade_date=trade_date)

    async def get_sw_daily(self, ts_code=None, trade_date=None, start_date=None, end_date=None, **kwargs):
        from .api.sw_daily import fetch_sw_daily
        return await fetch_sw_daily(self._get_conn(), ts_code=ts_code, trade_date=trade_date, start_date=start_date, end_date=end_date)

    async def get_ths_daily(self, ts_code=None, trade_date=None, start_date=None, end_date=None, **kwargs):
        from .api.ths_daily import fetch_ths_daily
        return await fetch_ths_daily(self._get_conn(), ts_code=ts_code, trade_date=trade_date, start_date=start_date, end_date=end_date)

    async def get_forecast(self, ts_code=None, start_date=None, end_date=None, **kwargs):
        from .api.financial import fetch_forecast
        return await fetch_forecast(self._get_conn(), ts_code=ts_code, start_date=start_date, end_date=end_date)

    async def get_express(self, ts_code=None, start_date=None, end_date=None, **kwargs):
        from .api.financial import fetch_express
        return await fetch_express(self._get_conn(), ts_code=ts_code, start_date=start_date, end_date=end_date)

    async def get_limit_step(self, ts_code=None, trade_date=None, start_date=None, end_date=None, **kwargs):
        from .api.limit_step import fetch_limit_step
        return await fetch_limit_step(self._get_conn(), ts_code=ts_code, trade_date=trade_date, start_date=start_date, end_date=end_date)

    async def get_moneyflow_ind_dc(self, trade_date=None, start_date=None, end_date=None, **kwargs):
        from .api.moneyflow_ind_dc import fetch_moneyflow_ind_dc
        return await fetch_moneyflow_ind_dc(self._get_conn(), trade_date=trade_date, start_date=start_date, end_date=end_date)

    async def get_dividend(self, ts_code=None, record_date=None, ex_date=None, **kwargs):
        from .api.dividend import fetch_dividend
        return await fetch_dividend(self._get_conn(), ts_code=ts_code, record_date=record_date, ex_date=ex_date)

    @staticmethod
    def _to_ts_code(symbol: str) -> str:
        code = str(symbol).zfill(6)
        if code.startswith(("60", "68", "90")):
            return f"{code}.SH"
        elif code.startswith(("0", "3", "20")):
            return f"{code}.SZ"
        elif code.startswith(("4", "8")):
            return f"{code}.BJ"
        return f"{code}.SZ"
