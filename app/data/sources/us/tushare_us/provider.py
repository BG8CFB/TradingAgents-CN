"""Tushare US Provider — 使用独立 TUSHARE_US_TOKEN，积分门槛 ≥ 120。

Token：独立读取 TUSHARE_US_TOKEN（回退到 TUSHARE_TOKEN），
与 A 股 / 港股的凭据与积分完全隔离。
仅覆盖主要美股 + 中概股。不支持公司行为和新闻。

结构性模板（连接管理 / 委托吞错 / 域分发）在
app/data/sources/tushare_common/base_provider.py；本类只声明市场差异。
美股代码转换（.N/.O/.A 后缀解析、三级缓存 + 分布式锁）保留在
code_resolver.py，经 ``_resolve_ts_code`` 钩子注入。
"""

from app.data.sources.tushare_common.base_provider import TushareBaseProvider
from app.data.sources.us.tushare_us.code_resolver import get_us_ts_code


class TushareUSProvider(TushareBaseProvider):
    """Tushare 美股数据源 Provider。"""

    # 域 → Tushare US endpoint 绑定表
    DOMAIN_ENDPOINTS = {
        "basic_info": "us_basic",
        "trade_calendar": "us_tradecal",
        "daily_quotes": "us_daily",
        "daily_indicators": "us_daily_adj",
        "adj_factors": "us_adjfactor",
    }
    FINANCIAL_ENDPOINTS = {
        "income": "us_income",
        "balance": "us_balancesheet",
        "cashflow": "us_cashflow",
        "indicator": "us_fina_indicator",
    }
    DEFAULT_EXCHANGE = "NYSE"
    PROBE_ENDPOINT = "us_basic"
    MIN_CREDITS = 120

    def __init__(self):
        super().__init__(name="tushare_us", market="US")

    async def _resolve_ts_code(self, symbol: str) -> str:
        """美股代码 → Tushare ts_code（基于交易所的后缀解析，带缓存）。"""
        return await get_us_ts_code(symbol, api=self._get_api())
