"""TushareBaseProvider — HK/US Tushare Provider 共用基类。

吸收三段结构性重复：
1. ``_get_api`` / ``connect`` / ``is_available``：委托 TushareClient
   （Token 解析、试探探测、错误分类、一次性重连）。
2. 各 ``get_xxx`` 的"委托 + 吞错"模板：业务异常在 Provider 层统一降级为
   ``return None``（异常细节由调用模板 call_tushare 记录日志）。
3. 域 → Tushare endpoint 的绑定表：子类声明 ``DOMAIN_ENDPOINTS``，
   基类按表分发，市场差异（endpoint 名、代码转换、报表路由）由子类注入。

市场差异保留在子类：
- endpoint 名称（hk_daily / us_daily / ...）
- 代码转换（HK zfill(5) / US code_resolver）
- 报表类型路由表（hk_income / us_income / ...）
"""

import logging
from typing import Dict, Optional

import pandas as pd

from app.data.sources.base.exceptions import DataSourceError
from app.data.sources.base.provider import BaseProvider
from app.data.sources.tushare_common.caller import call_tushare
from app.data.sources.tushare_common.client import TushareClient

logger = logging.getLogger(__name__)


def _compact(date_str) -> str:
    """YYYY-MM-DD → YYYYMMDD；空值返回空字符串。"""
    return str(date_str).replace("-", "") if date_str else ""


class TushareBaseProvider(BaseProvider):
    """Tushare HK/US Provider 基类（CN 有大量独有域，保留独立 Provider）。"""

    # 子类必须声明：domain → Tushare endpoint 名
    DOMAIN_ENDPOINTS: Dict[str, str] = {}
    # 财务报表类型 → endpoint 名（缺省回落到 income）
    FINANCIAL_ENDPOINTS: Dict[str, str] = {}
    DEFAULT_EXCHANGE: str = "SSE"
    # hk_tradecal 带 exchange 参数服务端返回 0 行（实测 2026-08），HK 子类置 True 省略
    TRADE_CAL_OMIT_EXCHANGE: bool = False
    PROBE_ENDPOINT: str = "stock_basic"
    MIN_CREDITS: int = 0

    def __init__(self, name: str, market: str, client: Optional[TushareClient] = None):
        super().__init__(name=name, market=market)
        self._client = client or TushareClient(
            source_name=name,
            probe_endpoint=self.PROBE_ENDPOINT,
            probe_kwargs={"limit": 1} if self.PROBE_ENDPOINT != "stock_basic" else {"list_status": "L", "limit": 1},
            min_credits=self.MIN_CREDITS,
        )

    # ── 连接管理 ────────────────────────────────────────────

    def _get_api(self):
        return self._client.get_api()

    async def connect(self) -> bool:
        try:
            ok = await self._client.connect()
            self.connected = ok
            return ok
        except DataSourceError:
            # TokenInvalid / InsufficientCredits 等凭据类异常直接透传
            self.connected = False
            raise
        except Exception as e:
            logger.error(f"{self.name} 连接失败: {e}")
            self.connected = False
            return False

    def is_available(self) -> bool:
        return self.connected and self._get_api() is not None

    # ── 代码转换钩子 ─────────────────────────────────────────

    async def _resolve_ts_code(self, symbol: str) -> str:
        """市场代码 → Tushare ts_code。子类按市场规则覆写。"""
        return symbol

    # ── 委托 + 吞错模板 ──────────────────────────────────────

    async def _delegate(self, coro, label: str) -> Optional[pd.DataFrame]:
        """执行调用并在业务异常时降级为 None（异常已由底层记录日志）。"""
        try:
            return await coro
        except DataSourceError as e:
            logger.debug(f"{self.name} {label} 失败: {e}")
            return None
        except Exception as e:
            logger.error(f"{self.name} {label} 失败: {e}")
            return None

    async def _call(self, domain: str, context: str = "", **params) -> Optional[pd.DataFrame]:
        """按 DOMAIN_ENDPOINTS 分发一次调用（不吞错，供需要异常的调用方使用）。"""
        endpoint = self.DOMAIN_ENDPOINTS.get(domain)
        if endpoint is None:
            raise NotImplementedError(f"{self.name} 不支持 {domain}")
        return await call_tushare(self._get_api(), endpoint, self.name, domain, context, **params)

    # ── 通用域方法 ───────────────────────────────────────────

    async def get_stock_list(self, **kwargs) -> pd.DataFrame:
        return await self._delegate(self._call("basic_info", "全市场"), "股票列表")

    async def get_trade_calendar(
        self,
        exchange: str = None,
        start_date: str = None,
        end_date: str = None,
        **kwargs,
    ) -> pd.DataFrame:
        # hk_tradecal 实测（2026-08，5000 积分）：带 exchange 参数服务端返回 0 行，
        # 必须省略；CN/US 接口正常接受 exchange。由子类 TRADE_CAL_OMIT_EXCHANGE 控制。
        params: Dict[str, str] = {}
        if not self.TRADE_CAL_OMIT_EXCHANGE:
            params["exchange"] = exchange or self.DEFAULT_EXCHANGE
        if start_date:
            params["start_date"] = _compact(start_date)
        if end_date:
            params["end_date"] = _compact(end_date)
        return await self._delegate(self._call("trade_calendar", exchange or self.DEFAULT_EXCHANGE, **params), "交易日历")

    async def get_daily_quotes(self, symbol: str, start_date: str, end_date: str, **kwargs) -> pd.DataFrame:
        ts_code = await self._resolve_ts_code(symbol)
        return await self._delegate(
            self._call(
                "daily_quotes",
                ts_code,
                ts_code=ts_code,
                start_date=_compact(start_date),
                end_date=_compact(end_date),
            ),
            f"行情 {symbol}",
        )

    async def get_daily_indicators(self, symbol: str, start_date: str, end_date: str, **kwargs) -> pd.DataFrame:
        ts_code = await self._resolve_ts_code(symbol)
        return await self._delegate(
            self._call(
                "daily_indicators",
                ts_code,
                ts_code=ts_code,
                start_date=_compact(start_date),
                end_date=_compact(end_date),
            ),
            f"每日指标 {symbol}",
        )

    async def get_adj_factors(self, symbol: str, start_date: str, end_date: str, **kwargs) -> pd.DataFrame:
        ts_code = await self._resolve_ts_code(symbol)
        return await self._delegate(
            self._call(
                "adj_factors",
                ts_code,
                ts_code=ts_code,
                start_date=_compact(start_date),
                end_date=_compact(end_date),
            ),
            f"复权因子 {symbol}",
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
        stmt = statement_type or "income"
        endpoint = self.FINANCIAL_ENDPOINTS.get(stmt, self.FINANCIAL_ENDPOINTS.get("income"))
        params: Dict[str, str] = {"ts_code": ts_code}
        if start_date:
            params["start_date"] = _compact(start_date)
        if end_date:
            params["end_date"] = _compact(end_date)
        return await self._delegate(
            call_tushare(
                self._get_api(),
                endpoint,
                self.name,
                "financial_data",
                f"{ts_code} ({stmt})",
                **params,
            ),
            f"财务 {symbol} ({stmt})",
        )

    async def get_market_quotes(self, symbols=None, **kwargs) -> pd.DataFrame:
        if "market_quotes" not in self.DOMAIN_ENDPOINTS:
            raise NotImplementedError(f"{self.name} 不支持 get_market_quotes")
        return await self._delegate(self._call("market_quotes", "全市场"), "实时行情")
