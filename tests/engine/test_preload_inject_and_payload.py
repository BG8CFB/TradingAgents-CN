"""预加载修复的守卫测试。

覆盖两处本机修复：
1. 「指数行情」预加载注入**基准指数**而不是被分析的个股代码
   （此前注入 ticker → 每次个股分析都返回「指数行情数据暂不可用: 002747」）。
2. 预加载结果若是**错误载荷**（工具不抛异常、只返回 {"status":"error",...}），
   必须能被识别出来，否则日志会把错误载荷记成「预加载成功」。
"""

from app.engine.orchestrator.agents import _looks_like_error_payload, _resolve_inject_args
from app.engine.tools.datasources.registry import get_spec_by_id


def _spec():
    return get_spec_by_id("market_quotes")


class TestBenchmarkIndexInjection:
    """「指数行情」预加载必须拿到指数代码。"""

    def test_inject_args_is_callable_not_literal_ticker(self):
        spec = _spec()
        assert spec is not None
        assert callable(spec.inject_args["stock_code"]), (
            "指数行情预加载必须用可调用解析器（按市场给基准指数），"
            "写死 'ticker' 会让每次个股分析都失败"
        )

    def test_cn_stock_resolves_to_benchmark_index(self):
        args = _resolve_inject_args(_spec(), {"ticker": "002747", "trade_date": "2026-10-08"})
        assert args["stock_code"] == "000001.SH"

    def test_never_passes_the_analysed_stock_code(self):
        for ticker in ("002747", "605589", "600602"):
            args = _resolve_inject_args(_spec(), {"ticker": ticker, "trade_date": "2026-10-08"})
            assert args["stock_code"] != ticker


class TestErrorPayloadDetection:
    """错误载荷识别（决定日志记「成功」还是「返回错误载荷」）。"""

    def test_detects_status_error_payload(self):
        assert _looks_like_error_payload(
            '{\n  "status": "error",\n  "data": "指数行情数据暂不可用: 002747（请先同步 market_quotes 数据）",\n'
            '  "error_code": "DATA_FETCH_ERROR"\n}'
        )

    def test_detects_compact_error_payload(self):
        assert _looks_like_error_payload('{"status":"error","error_code":"DATA_FETCH_ERROR"}')

    def test_real_data_is_not_flagged(self):
        assert not _looks_like_error_payload(
            "[{\"ts_code\": \"002747.SZ\", \"trade_date\": \"20261008\", \"close\": 26.86}]"
        )
        assert not _looks_like_error_payload("# Index: 000001.SH\nclose=3842.19")
