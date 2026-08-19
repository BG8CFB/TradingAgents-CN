"""Tushare HK Provider — 委托 tushare_common 基类调用 Tushare 港股 API。

Token：独立读取 TUSHARE_HK_TOKEN（回退到 TUSHARE_TOKEN），
与 A 股 / 美股的凭据与积分完全隔离。
积分门槛 ≥ 2000。
覆盖: 基础信息 / 行情 / 复权 / 财务 / 南向持股。
不支持: 公司行为 / 新闻（必须由 AKShare HK 承担）。

结构性模板（连接管理 / 委托吞错 / 域分发）在
app/data/sources/tushare_common/base_provider.py；本类只声明市场差异。
"""

import pandas as pd

from app.data.sources.hk.tushare_hk.api.hk_basic import fetch_stock_list
from app.data.sources.hk.tushare_hk.api.hk_daily import fetch_daily_quotes
from app.data.sources.hk.tushare_hk.api.hk_financials import fetch_financial_data
from app.data.sources.tushare_common.base_provider import TushareBaseProvider


class TushareHKProvider(TushareBaseProvider):
    """Tushare 港股数据源 Provider。"""

    # 域 → Tushare HK endpoint 绑定表
    DOMAIN_ENDPOINTS = {
        "basic_info": "hk_basic",
        "trade_calendar": "hk_tradecal",
        "daily_quotes": "hk_daily",
        "daily_indicators": "hk_daily_adj",
        "adj_factors": "hk_adjfactor",
        "market_quotes": "rt_hk_k",
    }
    FINANCIAL_ENDPOINTS = {
        "income": "hk_income",
        "balance": "hk_balancesheet",
        "cashflow": "hk_cashflow",
        "indicator": "hk_fina_indicator",
    }
    DEFAULT_EXCHANGE = "HKEX"
    TRADE_CAL_OMIT_EXCHANGE = True  # hk_tradecal 带 exchange 返回 0 行，实测须省略
    PROBE_ENDPOINT = "hk_basic"
    MIN_CREDITS = 2000

    def __init__(self):
        super().__init__(name="tushare_hk", market="HK")

    # ── 市场差异：代码转换 ───────────────────────────────────

    async def _resolve_ts_code(self, symbol: str) -> str:
        return self._to_hk_ts_code(symbol)

    @staticmethod
    def _to_hk_ts_code(symbol: str) -> str:
        """标准 5 位代码 → Tushare HK ts_code (5位.HK)。"""
        code = str(symbol).replace(".HK", "").zfill(5)
        return f"{code}.HK"

    # ── 显式委托 api/ 子模块（结构约定：provider 不直连 Tushare 原生接口）──

    async def get_stock_list(self, **kwargs) -> pd.DataFrame:
        return await self._delegate(fetch_stock_list(self._get_api()), "股票列表")

    async def get_daily_quotes(self, symbol: str, start_date: str, end_date: str, **kwargs) -> pd.DataFrame:
        ts_code = await self._resolve_ts_code(symbol)
        return await self._delegate(
            fetch_daily_quotes(self._get_api(), ts_code, start_date, end_date),
            f"行情 {symbol}",
        )

    async def get_financial_data(
        self,
        symbol: str,
        start_date: str,
        end_date: str,
        statement_type: str = "",
        **kwargs,
    ) -> pd.DataFrame:
        ts_code = await self._resolve_ts_code(symbol)
        return await self._delegate(
            fetch_financial_data(
                self._get_api(),
                ts_code,
                statement_type or "income",
                start_date,
                end_date,
            ),
            f"财务 {symbol} ({statement_type or 'income'})",
        )
