"""熔断器：业务性「空结果」不得触发熔断（守卫用例）。

背景：逐标的遍历的域（两融 / 龙虎榜 / 资金流 / 大宗）天然只有部分标的有数据。
若把空结果也计入失败，连续 FAILURE_THRESHOLD 次空结果就会打开熔断 →
同域后续标的被整体短路 —— 现象是「SYNC_SUCCESS 但只入库标的表开头几百只」，
库里表现为整段日期空白 / 不连续。

修法（两处，缺一不可）：
  ① circuit_breaker.record_failure 对 _NON_FAILURE_CODES 提前 return（不计失败）；
  ② fallback_router 的空数据分支显式传 error_code=EMPTY_RESULT（否则豁免到不了）。
"""

import inspect

from app.data.processor.circuit_breaker import FAILURE_THRESHOLD, CircuitBreaker
from app.data.schema.base.enums import CircuitState
from app.data.sources.base.error_codes import DataErrorCode


def _state(cb: CircuitBreaker, src: str = "tushare", dom: str = "margin_trading") -> str:
    s = cb.get_state(src, domain=dom, market="CN")
    return s.value if hasattr(s, "value") else s


class TestNonFailureCodesDoNotTrip:
    def test_empty_result_never_trips(self):
        cb = CircuitBreaker()
        for _ in range(FAILURE_THRESHOLD * 5):
            cb.record_failure(
                "tushare", domain="margin_trading", market="CN",
                error_code=DataErrorCode.EMPTY_RESULT,
            )
        assert _state(cb) == CircuitState.CLOSED.value

    def test_symbol_not_found_and_not_supported_never_trip(self):
        cb = CircuitBreaker()
        for code in (DataErrorCode.SYMBOL_NOT_FOUND, DataErrorCode.NOT_SUPPORTED):
            for _ in range(FAILURE_THRESHOLD * 3):
                cb.record_failure(
                    "tushare", domain="dragon_tiger", market="CN", error_code=code
                )
        assert _state(cb, dom="dragon_tiger") == CircuitState.CLOSED.value

    def test_empty_results_do_not_accumulate(self):
        """空结果不能「垫」出熔断：灌一堆空结果后，再来不足阈值的真错仍不该熔断。"""
        cb = CircuitBreaker()
        for _ in range(10):
            cb.record_failure(
                "tushare", domain="money_flow", market="CN",
                error_code=DataErrorCode.EMPTY_RESULT,
            )
        for _ in range(FAILURE_THRESHOLD - 1):
            cb.record_failure(
                "tushare", domain="money_flow", market="CN",
                error_code=DataErrorCode.NETWORK_TIMEOUT,
            )
        assert _state(cb, dom="money_flow") == CircuitState.CLOSED.value

    def test_real_errors_still_trip(self):
        """真错必须照旧熔断 —— 豁免不能把熔断器废掉。"""
        cb = CircuitBreaker()
        for _ in range(FAILURE_THRESHOLD):
            cb.record_failure(
                "tushare", domain="daily_quotes", market="CN",
                error_code=DataErrorCode.NETWORK_TIMEOUT,
            )
        assert _state(cb, dom="daily_quotes") == CircuitState.OPEN.value

    def test_router_passes_empty_result_code(self):
        """fallback_router 的空数据分支必须显式传 EMPTY_RESULT，豁免才到得了。"""
        from app.data.processor import fallback_router as fr

        src = inspect.getsource(fr)
        block = src[src.index("raw_data.empty") :][:900]
        assert "DataErrorCode.EMPTY_RESULT" in block, "空数据分支必须传 EMPTY_RESULT"
