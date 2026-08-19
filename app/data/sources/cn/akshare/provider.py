"""AKShare CN Provider — 调用 api/ 子模块获取原始数据。"""

import logging

import pandas as pd

from app.data.sources.base.provider import BaseProvider

logger = logging.getLogger(__name__)


def _filter_by_date(
    df: pd.DataFrame,
    start_date: str,
    end_date: str,
    date_cols: list[str] | None = None,
) -> pd.DataFrame:
    """对 DataFrame 做内存日期过滤。

    AKShare 部分底层 API 不支持日期参数，需在 Provider 层按
    trade_date / date / 时间 等列做内存过滤。

    Args:
        df: 原始 DataFrame。
        start_date: 起始日期（YYYY-MM-DD 或 YYYYMMDD 或空串）。
        end_date: 截止日期（同上或空串）。
        date_cols: 候选日期列名列表，按优先级尝试。
    """
    if df is None or df.empty:
        return df
    if not start_date and not end_date:
        return df

    if date_cols is None:
        date_cols = ["trade_date", "date", "日期", "时间"]

    sd = start_date.replace("-", "") if start_date else ""
    ed = end_date.replace("-", "") if end_date else ""

    date_col = None
    for col in date_cols:
        if col in df.columns:
            date_col = col
            break
    if date_col is None:
        return df

    def _norm(val) -> str:
        """统一日期值为 YYYYMMDD 字符串用于比较。"""
        s = str(val)[:10].replace("-", "")
        return s

    # 分别计算上下界条件再合并：此前 mask 被两次比较覆盖，
    # 第二次 bool Series 与字符串比较直接抛 TypeError
    normed = df[date_col].apply(_norm)
    mask = pd.Series(True, index=df.index)
    if sd:
        mask &= normed >= sd
    if ed:
        mask &= normed <= ed
    return df[mask].copy()


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
        self,
        symbol: str,
        start_date: str,
        end_date: str,
        statement_type: str = "",
        **kwargs,
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

    async def get_market_quotes(self, symbols=None, **kwargs) -> pd.DataFrame:
        from .api.quotes_batch import fetch_batch_quotes

        # 此前硬编码传空列表，导致任何调用都"所有策略链均无数据 (codes=0)"
        return await fetch_batch_quotes(list(symbols) if symbols else [])

    async def get_intraday_quotes(
        self, symbol: str, start_date: str, end_date: str, **kwargs
    ) -> pd.DataFrame:
        from .api.intraday_quotes import fetch_intraday_quotes

        freq = kwargs.get("freq", "30")
        df = await fetch_intraday_quotes(symbol, period=freq)
        # EM 分钟线列名 "时间"，新浪 stock_zh_a_minute 回退列名 "day"，
        # 截取前 10 字符做日期过滤
        return _filter_by_date(
            df, start_date, end_date, date_cols=["时间", "day", "date", "trade_date"]
        )

    async def get_money_flow(
        self, symbol: str, start_date: str, end_date: str, **kwargs
    ) -> pd.DataFrame:
        from .api.money_flow import fetch_money_flow_by_symbol

        df = await fetch_money_flow_by_symbol(symbol)
        return _filter_by_date(
            df, start_date, end_date, date_cols=["日期", "date", "trade_date"]
        )

    async def get_margin_trading(
        self, symbol: str, start_date: str, end_date: str, **kwargs
    ) -> pd.DataFrame:
        from .api.margin_trading import fetch_margin_trading

        df = await fetch_margin_trading(symbol)
        return _filter_by_date(
            df,
            start_date,
            end_date,
            date_cols=["日期", "信用交易日期", "date", "trade_date"],
        )

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
