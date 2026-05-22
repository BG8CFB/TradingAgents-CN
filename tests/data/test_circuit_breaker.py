"""熔断器三态状态机单元测试 — 匹配新架构 CircuitBreaker API"""

import time

from app.data.processor.circuit_breaker import CircuitBreaker
from app.data.schema.base.enums import CircuitState


class TestCircuitBreakerStates:
    """三态转换测试"""

    def test_initial_state_is_closed(self):
        cb = CircuitBreaker()
        assert cb.get_state("tushare", "daily_quotes") == CircuitState.CLOSED
        assert not cb.is_open("tushare", "daily_quotes")

    def test_closed_to_open_after_threshold(self):
        cb = CircuitBreaker()
        source, domain = "tushare", "daily_quotes"

        cb.record_failure(source, domain)
        cb.record_failure(source, domain)
        assert cb.get_state(source, domain) == CircuitState.CLOSED

        # 第 3 次失败触发熔断
        cb.record_failure(source, domain)
        assert cb.get_state(source, domain) == CircuitState.OPEN
        assert cb.is_open(source, domain)

    def test_open_to_half_open_after_cooldown(self):
        cb = CircuitBreaker()
        source, domain = "tushare", "daily_quotes"

        # 触发熔断
        for _ in range(3):
            cb.record_failure(source, domain)
        assert cb.get_state(source, domain) == CircuitState.OPEN

        # 模拟冷却到期
        state = cb._get_state(source, domain)
        state["opened_at"] = time.time() - state["cooldown"] - 1

        # 检查状态应变为 HALF_OPEN
        assert not cb.is_open(source, domain)
        assert cb.get_state(source, domain) == CircuitState.HALF_OPEN

    def test_half_open_to_closed_on_success(self):
        cb = CircuitBreaker()
        source, domain = "tushare", "daily_quotes"

        # 触发熔断
        for _ in range(3):
            cb.record_failure(source, domain)

        # 手动设置为 HALF_OPEN
        state = cb._get_state(source, domain)
        state["state"] = CircuitState.HALF_OPEN

        cb.record_success(source, domain)
        assert cb.get_state(source, domain) == CircuitState.CLOSED

    def test_half_open_to_open_on_failure(self):
        cb = CircuitBreaker()
        source, domain = "tushare", "daily_quotes"

        # 触发熔断
        for _ in range(3):
            cb.record_failure(source, domain)

        # 手动设置为 HALF_OPEN
        state = cb._get_state(source, domain)
        state["state"] = CircuitState.HALF_OPEN

        cb.record_failure(source, domain)
        assert cb.get_state(source, domain) == CircuitState.OPEN

    def test_success_resets_failure_count(self):
        cb = CircuitBreaker()
        source, domain = "tushare", "daily_quotes"

        cb.record_failure(source, domain)
        cb.record_failure(source, domain)
        cb.record_success(source, domain)

        # 失败已清空，需要再 3 次才熔断
        cb.record_failure(source, domain)
        assert cb.get_state(source, domain) == CircuitState.CLOSED

    def test_independent_domains(self):
        cb = CircuitBreaker()
        for _ in range(3):
            cb.record_failure("tushare", "daily_quotes")
        assert cb.is_open("tushare", "daily_quotes")
        assert not cb.is_open("tushare", "financial")

    def test_independent_sources(self):
        cb = CircuitBreaker()
        for _ in range(3):
            cb.record_failure("tushare", "daily_quotes")
        assert cb.is_open("tushare", "daily_quotes")
        assert not cb.is_open("akshare", "daily_quotes")

    def test_cooldown_increases_with_repeated_opens(self):
        cb = CircuitBreaker()
        source, domain = "tushare", "daily_quotes"

        # 第 1 次熔断
        for _ in range(3):
            cb.record_failure(source, domain)
        state1 = cb._get_state(source, domain)
        cd1 = state1["cooldown"]
        assert cd1 >= 60  # 至少 60 秒

        # 模拟冷却到期 + 半开 + 再次失败
        state1["opened_at"] = time.time() - state1["cooldown"] - 1
        state1["state"] = CircuitState.HALF_OPEN
        cb.record_failure(source, domain)  # 再次熔断

        state2 = cb._get_state(source, domain)
        cd2 = state2["cooldown"]
        assert cd2 > cd1  # 冷却时间应增加
