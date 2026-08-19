"""熔断器 (source, market, domain) 三段键测试。

Phase 2 改造点：熔断键加入 market 维度后——

1. HK 域熔断不影响 CN 同名源（跨市场隔离）
2. 存量两段式调用 ``record_failure(source, domain)`` 仍工作
   （market 缺省 ""，与历史行为一致）
"""

from app.data.processor.circuit_breaker import CircuitBreaker
from app.data.schema.base.enums import CircuitState


class TestMarketKeyIsolation:
    """market 维度隔离。"""

    def test_hk_trip_does_not_affect_cn(self):
        cb = CircuitBreaker()
        for _ in range(3):
            cb.record_failure("tushare", domain="daily_quotes", market="HK")

        assert cb.is_open("tushare", domain="daily_quotes", market="HK") is True
        assert cb.get_state("tushare", domain="daily_quotes", market="HK") == CircuitState.OPEN

        # CN / US 同名源、同 domain 不受影响
        assert cb.is_open("tushare", domain="daily_quotes", market="CN") is False
        assert cb.is_open("tushare", domain="daily_quotes", market="US") is False
        assert cb.get_state("tushare", domain="daily_quotes", market="CN") == CircuitState.CLOSED

    def test_market_and_domain_both_isolate(self):
        cb = CircuitBreaker()
        for _ in range(3):
            cb.record_failure("tushare_hk", domain="daily_quotes", market="HK")

        assert cb.is_open("tushare_hk", domain="daily_quotes", market="HK")
        # 同市场不同 domain 不受影响
        assert not cb.is_open("tushare_hk", domain="financial_data", market="HK")

    def test_success_in_cn_does_not_clear_hk(self):
        cb = CircuitBreaker()
        for _ in range(3):
            cb.record_failure("tushare", domain="daily_quotes", market="HK")

        # CN 成功不应影响 HK 的 OPEN 状态
        cb.record_success("tushare", domain="daily_quotes", market="CN")
        assert cb.is_open("tushare", domain="daily_quotes", market="HK")

        # HK 恢复：半开后成功才闭合
        state = cb._get_state("tushare", domain="daily_quotes", market="HK")
        state["state"] = CircuitState.HALF_OPEN
        cb.record_success("tushare", domain="daily_quotes", market="HK")
        assert cb.get_state("tushare", domain="daily_quotes", market="HK") == CircuitState.CLOSED


class TestLegacyTwoArgCalls:
    """存量两段式调用兼容（market 缺省 ""）。"""

    def test_two_arg_record_and_query_still_work(self):
        cb = CircuitBreaker()
        for _ in range(3):
            cb.record_failure("akshare", "financial_data")  # (source, domain)

        assert cb.is_open("akshare", "financial_data") is True

    def test_two_arg_failure_count_isolated_from_three_arg(self):
        cb = CircuitBreaker()
        # 两段式调用 2 次（不触发熔断）
        cb.record_failure("akshare", "financial_data")
        cb.record_failure("akshare", "financial_data")
        # 三段式调用走独立键
        cb.record_failure("akshare", domain="financial_data", market="CN")
        assert not cb.is_open("akshare", "financial_data")
        assert not cb.is_open("akshare", domain="financial_data", market="CN")
