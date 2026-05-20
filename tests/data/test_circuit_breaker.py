"""熔断器三态状态机单元测试"""

import time

from app.data.processor.circuit_breaker import CircuitBreaker, CircuitState


class TestCircuitBreakerStates:
    """三态转换测试"""

    def test_initial_state_is_closed(self):
        cb = CircuitBreaker()
        assert cb.get_state("tushare", "daily_quotes") == CircuitState.CLOSED
        assert not cb.is_open("tushare", "daily_quotes")

    def test_closed_to_open_after_threshold(self):
        cb = CircuitBreaker(failure_threshold=3, window_seconds=300)
        source, domain = "tushare", "daily_quotes"

        cb.record_failure(source, domain, "network")
        cb.record_failure(source, domain, "network")
        assert cb.get_state(source, domain) == CircuitState.CLOSED

        cb.record_failure(source, domain, "network")
        assert cb.get_state(source, domain) == CircuitState.OPEN
        assert cb.is_open(source, domain)

    def test_open_to_half_open_after_cooldown(self):
        cb = CircuitBreaker(failure_threshold=1, window_seconds=300)
        source, domain = "tushare", "daily_quotes"

        cb.record_failure(source, domain, "network")
        assert cb.get_state(source, domain) == CircuitState.OPEN

        # 手动模拟冷却到期
        circuit = cb._get_circuit(source, domain)
        circuit.next_retry_at = time.monotonic() - 1  # 已过期

        state = cb.get_state(source, domain)
        assert state == CircuitState.HALF_OPEN

    def test_half_open_to_closed_on_success(self):
        cb = CircuitBreaker(failure_threshold=1, window_seconds=300)
        source, domain = "tushare", "daily_quotes"

        cb.record_failure(source, domain, "network")
        circuit = cb._get_circuit(source, domain)
        circuit.state = CircuitState.HALF_OPEN

        cb.record_success(source, domain)
        assert cb.get_state(source, domain) == CircuitState.CLOSED

    def test_half_open_to_open_on_failure(self):
        cb = CircuitBreaker(failure_threshold=1, window_seconds=300)
        source, domain = "tushare", "daily_quotes"

        cb.record_failure(source, domain, "network")
        circuit = cb._get_circuit(source, domain)
        circuit.state = CircuitState.HALF_OPEN

        cb.record_failure(source, domain, "network")
        assert cb.get_state(source, domain) == CircuitState.OPEN

    def test_success_resets_failure_count(self):
        cb = CircuitBreaker(failure_threshold=3, window_seconds=300)
        source, domain = "tushare", "daily_quotes"

        cb.record_failure(source, domain, "network")
        cb.record_failure(source, domain, "network")
        cb.record_success(source, domain)

        # 失败计数已重置，需要再 3 次才熔断
        cb.record_failure(source, domain, "network")
        assert cb.get_state(source, domain) == CircuitState.CLOSED

    def test_independent_domains(self):
        cb = CircuitBreaker(failure_threshold=1)
        cb.record_failure("tushare", "daily_quotes", "network")
        assert cb.is_open("tushare", "daily_quotes")
        assert not cb.is_open("tushare", "financial")

    def test_independent_sources(self):
        cb = CircuitBreaker(failure_threshold=1)
        cb.record_failure("tushare", "daily_quotes", "network")
        assert cb.is_open("tushare", "daily_quotes")
        assert not cb.is_open("akshare", "daily_quotes")

    def test_manual_reset(self):
        cb = CircuitBreaker(failure_threshold=1)
        source, domain = "tushare", "daily_quotes"

        cb.record_failure(source, domain, "network")
        assert cb.is_open(source, domain)

        cb.reset(source, domain)
        assert cb.get_state(source, domain) == CircuitState.CLOSED


class TestCircuitBreakerCooldown:
    """阶梯冷却策略测试"""

    def test_cooldown_increases_with_opens(self):
        cb = CircuitBreaker(failure_threshold=1)

        # 第 1 次熔断: 60s
        cd1 = cb._cooldown_for_open_count(1, "network")
        assert cd1 == 60

        # 第 2 次: 120s
        cd2 = cb._cooldown_for_open_count(2, "network")
        assert cd2 == 120

        # 第 3 次: 300s
        cd3 = cb._cooldown_for_open_count(3, "network")
        assert cd3 == 300

        # 第 4 次+: 600s
        cd4 = cb._cooldown_for_open_count(4, "network")
        assert cd4 == 600

        cd5 = cb._cooldown_for_open_count(10, "network")
        assert cd5 == 600

    def test_error_type_multipliers(self):
        cb = CircuitBreaker(failure_threshold=1)

        # rate_limited: 60 * 2 = 120
        assert cb._cooldown_for_open_count(1, "rate_limited") == 120

        # auth_failed: 60 * 5 = 300
        assert cb._cooldown_for_open_count(1, "auth_failed") == 300

        # server_error: 60 * 1.5 = 90
        assert cb._cooldown_for_open_count(1, "server_error") == 90
