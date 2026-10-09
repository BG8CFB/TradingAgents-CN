"""数据源工具的事件循环守卫：工具层必须走原生 async，不得经 run_async 桥。

背景：工具 handler 原本是同步函数，内部经 `run_async` 桥读数据层。当调用发生在
「已有运行中的事件循环、但注册的主循环不可用」的上下文时，`run_async` 会退化到
`asyncio.run()` 并抛：

    asyncio.run() cannot be called from a running event loop

后果是**库里明明有数据却读不到**，工具返回 `DATA_FETCH_ERROR`（实测：财务报表 /
资金流向 / 两融），报告里还会给出"请先同步数据"的误导提示。

本测试锁定：工具 handler 为协程函数，且在运行中的事件循环里直接 await 即可取到数据，
`run_async` 一旦被调用即判定失败。
"""

from __future__ import annotations

import inspect

import pytest

from app.data.core.interface import DataInterface
from app.engine.tools.common import data_access
from app.engine.tools.datasources import capital_flow, china_market, fundamentals, market

# 需要原生 async 的工具（全部按 read_with_refresh 调用点梳理）
ASYNC_HANDLERS = {
    capital_flow: ("get_money_flow", "get_margin_trade"),
    fundamentals: ("get_stock_fundamentals", "get_company_performance_unified", "get_stock_basic_info"),
    china_market: ("get_china_market_overview", "get_dragon_tiger_inst", "get_block_trade"),
    market: ("get_stock_data", "get_stock_data_minutes", "get_index_data", "get_stock_indicators"),
}

MONEY_FLOW_ROW = {"symbol": "002747", "trade_date": "2026-09-30", "net_mm_amount": 12_345_678.0}
PERF_ROW = {"symbol": "002747", "report_period": "2026-06-30", "revenue": 2_577_506_515.4, "net_profit": 161_325_506.86}


class _FakeDataInterface:
    """只实现读路径的假数据层；read 直接返回数据，refresh 不应被走到。"""

    def __init__(self, rows):
        self._rows = rows
        self.read_calls: list = []
        self.refresh_calls: list = []

    async def read(self, market, domain, symbol=None, **kwargs):
        self.read_calls.append((market, domain, symbol))
        return {"data": self._rows, "freshness": {"status": "fresh"}}

    async def refresh(self, *args, **kwargs):  # pragma: no cover - 有数据时不应触发
        self.refresh_calls.append((args, kwargs))
        raise AssertionError("库内有数据时不应触发按需刷新")


@pytest.fixture
def fake_di(monkeypatch):
    def _install(rows):
        fake = _FakeDataInterface(rows)
        monkeypatch.setattr(DataInterface, "get_instance", classmethod(lambda cls: fake))
        return fake

    return _install


@pytest.fixture(autouse=True)
def _run_async_forbidden(monkeypatch):
    """把同步桥换成"一调用就失败"，确保工具层不再依赖它。"""

    def _boom(*args, **kwargs):  # pragma: no cover - 出现即测试失败
        raise AssertionError("工具层不应再经 run_async 桥（会触发嵌套事件循环报错）")

    monkeypatch.setattr(data_access, "run_async", _boom, raising=False)


class TestHandlersAreNativeAsync:
    @pytest.mark.parametrize("module,names", list(ASYNC_HANDLERS.items()), ids=lambda v: getattr(v, "__name__", ""))
    def test_handlers_are_coroutine_functions(self, module, names):
        for name in names:
            fn = getattr(module, name)
            assert inspect.iscoroutinefunction(fn), f"{module.__name__}.{name} 必须是 async（直连数据层）"

    def test_read_with_refresh_async_exists(self):
        assert inspect.iscoroutinefunction(data_access.read_with_refresh_async)

    def test_sync_variant_kept_for_sync_callers(self):
        """同步版保留（供无事件循环的脚本/线程使用），但 async 调用方不得再用它。"""
        assert not inspect.iscoroutinefunction(data_access.read_with_refresh)


class TestReadsInsideRunningLoop:
    @pytest.mark.asyncio
    async def test_money_flow_reads_data(self, fake_di):
        fake_di([MONEY_FLOW_ROW])
        out = await capital_flow.get_money_flow(ts_code="002747.SZ")
        assert "DATA_FETCH_ERROR" not in out, out
        assert "002747" in out or "net_mm_amount" in out or "12345678" in out

    @pytest.mark.asyncio
    async def test_company_performance_reads_data(self, fake_di):
        """财务报表：本次线上失败的主角。"""
        fake_di([PERF_ROW])
        out = await fundamentals.get_company_performance_unified(stock_code="002747", data_type="indicators")
        assert "DATA_FETCH_ERROR" not in out, out

    @pytest.mark.asyncio
    async def test_company_performance_falls_back_when_statement_type_misses(self, monkeypatch):
        """指定报表口径查空 → 回退不过滤再查，避免"库里有数据却报请先同步"。

        实测背景：本地 stock_financial_data 以 statement_type=income 落库，
        而 indicators 口径按 indicator 过滤 → 恒查空 → 误报"请先同步数据"。
        """

        class _FilterAwareFake:
            """按 filters 是否传入决定返回：带 filters 视为未命中。"""

            def __init__(self):
                self.read_filters: list = []

            async def read(self, market, domain, symbol=None, **kwargs):
                self.read_filters.append(kwargs.get("filters"))
                rows = [] if kwargs.get("filters") else [PERF_ROW]
                return {"data": rows, "freshness": {"status": "fresh"}}

            async def refresh(self, *args, **kwargs):  # pragma: no cover - 有数据不应触发
                raise AssertionError("库内有数据时不应触发按需刷新")

        fake = _FilterAwareFake()
        monkeypatch.setattr(DataInterface, "get_instance", classmethod(lambda cls: fake))

        out = await fundamentals.get_company_performance_unified(stock_code="002747", data_type="indicators")

        assert "DATA_FETCH_ERROR" not in out, out
        assert fake.read_filters[0] == {"statement_type": "indicator"}  # 先按报表口径查
        assert fake.read_filters[-1] is None  # 未命中 → 回退不过滤

    @pytest.mark.asyncio
    async def test_market_level_read_without_symbol_still_supported(self, fake_di):
        """资金流向支持市场级读取（symbol 为空）：有数据时直接返回，不触发刷新。"""
        fake = fake_di([MONEY_FLOW_ROW])
        out = await capital_flow.get_money_flow(query_type="market")
        assert "DATA_FETCH_ERROR" not in out, out
        assert fake.refresh_calls == []

    @pytest.mark.asyncio
    async def test_empty_result_returns_error_payload_without_bridge(self, fake_di):
        """库内无数据时按需刷新一次；本用例让刷新返回空，应给出错误载荷而非抛异常。"""
        fake = fake_di([])

        async def _empty_refresh(*args, **kwargs):
            return type("R", (), {"domains": {}})()

        fake.refresh = _empty_refresh
        out = await capital_flow.get_money_flow(ts_code="002747.SZ")
        assert "DATA_FETCH_ERROR" in out or "暂不可用" in out, out
