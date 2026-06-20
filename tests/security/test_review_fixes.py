"""代码审查第二轮修复的单元测试。

覆盖 6 项问题：
- P0-5: SlidingWindowCounter.get_count Redis-aware（预检读到的是真实计数）
- P0-3: SecretService 并发竞争 → DuplicateKeyError 容错
- P0-4: WebSocket fail-closed 在 accept 之后 close
- P1-1: circuit_breaker 添加 SERVICE_UNAVAILABLE 冷却倍率
- L1: operation_log_middleware 移除 operation_log_user 死代码
- L2: rate_limiter 在 Redis 不可用时返回 False（fail-closed）
"""

import asyncio
import time

import pytest

from tests.test_infra import SimulatedRedis


@pytest.fixture(autouse=True)
def _clear_memory_counters():
    """每个测试前后清理模块级 _memory_counters，防跨测试污染。

    SlidingWindowCounter 的内存降级路径使用模块级全局 _memory_counters；
    RateLimiter 内部也有自己的 _memory_counters 实例字段（不共享）。
    本 fixture 只清前者，避免与限流器逻辑耦合。
    """
    from app.data.storage.redis.counters import _memory_counters
    _memory_counters.clear()
    yield
    _memory_counters.clear()


# ---------------------------------------------------------------------------
# P0-5: SlidingWindowCounter.get_count Redis-aware
# ---------------------------------------------------------------------------


@pytest.fixture
def inject_sim_redis(monkeypatch):
    """注入 SimulatedRedis 到 counters 模块读取的 get_redis 路径。

    counters.py 通过标准 import 引用 app.data.storage.redis.client.get_redis，
    这里直接 patch 模块属性，让所有调用点拿到同一实例。
    """
    sim = SimulatedRedis()

    from app.data.storage.redis import client as redis_client_mod

    monkeypatch.setattr(redis_client_mod, "get_redis", lambda: sim)
    return sim


class TestSlidingWindowCounterRedisAware:
    """P0-5：预检与递增读到同一个 Redis 视图。"""

    @pytest.mark.asyncio
    async def test_get_count_zero_on_fresh_key(self, inject_sim_redis):
        from app.data.storage.redis.counters import SlidingWindowCounter

        counter = SlidingWindowCounter(window_seconds=60)
        assert await counter.get_count("ratelimit:tushare") == 0

    @pytest.mark.asyncio
    async def test_get_count_reflects_increment(self, inject_sim_redis):
        from app.data.storage.redis.counters import SlidingWindowCounter

        counter = SlidingWindowCounter(window_seconds=60)
        await counter.increment("ratelimit:tushare")
        # time.time() 在同一毫秒内可能返回相同值导致 member 冲突，主动错开
        await asyncio.sleep(0.002)
        await counter.increment("ratelimit:tushare")

        # 预检读出的计数应等于递增结果（修复前为 0，因为只读内存视图）
        assert await counter.get_count("ratelimit:tushare") == 2

    @pytest.mark.asyncio
    async def test_get_count_after_window_expiry(self, inject_sim_redis):
        """窗口外成员应被清理。"""
        from app.data.storage.redis.counters import SlidingWindowCounter

        counter = SlidingWindowCounter(window_seconds=60)
        await counter.increment("ratelimit:tushare")

        # 通过底层 SimulatedRedis 的 zset 直接注入一条过期成员
        # （SimulatedRedis.zadd 接受 {member: score}）
        old_score = time.time() - 120
        await inject_sim_redis.zadd("ratelimit:tushare", {"ancient": old_score})

        # get_count 应清理掉过期成员
        count = await counter.get_count("ratelimit:tushare")
        assert count == 1  # 仍包含刚 increment 的那条；过期那条被清掉

    @pytest.mark.asyncio
    async def test_get_count_without_redis_falls_back_to_memory(self, monkeypatch):
        """Redis 不可用时降级内存视图。"""
        from app.data.storage.redis import client as redis_client_mod
        from app.data.storage.redis.counters import SlidingWindowCounter

        # 让 get_redis 返回 None（模拟 Redis 未初始化）
        monkeypatch.setattr(redis_client_mod, "get_redis", lambda: None)

        counter = SlidingWindowCounter(window_seconds=60)
        # 通过内存视图递增
        await counter.increment("ratelimit:mem_only")
        # 内存视图应反映出来
        from app.data.storage.redis.counters import _memory_counters
        # 清理残留避免跨用例污染
        _memory_counters.pop("ratelimit:mem_only", None)
        await counter.increment("ratelimit:mem_only")
        assert await counter.get_count("ratelimit:mem_only") == 1
        _memory_counters.pop("ratelimit:mem_only", None)


# ---------------------------------------------------------------------------
# P0-3: SecretService 并发竞争容错
# ---------------------------------------------------------------------------


class TestSecretServiceRaceRecovery:
    """P0-3：并发首启下 DuplicateKeyError 后仍读到权威值。"""

    @pytest.mark.asyncio
    async def test_duplicate_key_recovers_from_db(self, sim_db):
        """update_one 抛错后，应能从 DB 读出权威值。

        场景：另一 worker 已写入 jwt_secret/csrf_secret。
        本 worker 的 find_one 拿不到（模拟时间差），但 update_one 因唯一索引冲突失败。
        修复后：catch 异常后从 DB 读出真实值。
        """
        import os
        import tempfile
        from pathlib import Path

        from app.services import secret_service as ss
        from app.core import database as db_mod

        original_db = db_mod.mongo_db
        original_file = ss._FALLBACK_FILE
        db_mod.mongo_db = sim_db
        ss._FALLBACK_FILE = Path(tempfile.mkdtemp()) / ".secrets.json"

        # 清空 system_secrets + 环境变量
        for name in ("jwt_secret", "csrf_secret"):
            await sim_db["system_secrets"].delete_one({"name": name})
        for k in ("JWT_SECRET", "CSRF_SECRET"):
            os.environ.pop(k, None)
        # 清空文件兜底
        if ss._FALLBACK_FILE.exists():
            ss._FALLBACK_FILE.unlink()

        try:
            # 预置"另一 worker 已写入"的真实值
            authoritative = {
                "jwt_secret": "AUTHORITATIVE_JWT_VALUE_FROM_OTHER_WORKER",
                "csrf_secret": "AUTHORITATIVE_CSRF_VALUE_FROM_OTHER_WORKER",
            }
            await sim_db["system_secrets"].insert_one(
                {"name": "jwt_secret", "value": authoritative["jwt_secret"]}
            )
            await sim_db["system_secrets"].insert_one(
                {"name": "csrf_secret", "value": authoritative["csrf_secret"]}
            )

            # 包装 collection：update_one 总是抛 DuplicateKeyError（模拟并发首启冲突）
            original_collection = sim_db["system_secrets"]
            update_calls = {"count": 0}

            # find_one 调用顺序契约（与 SecretService 主流程严格对应）：
            # 调用 1：jwt_secret 主流程 → 返回 None，强制走 update_one
            # 调用 2：jwt_secret update_one 抛错后异常恢复 → 返回 jwt 权威值
            # 调用 3：csrf_secret 主流程 → 返回 None
            # 调用 4：csrf_secret 异常恢复 → 返回 csrf 权威值
            # 用 (name, phase) 显式映射，避免奇偶次假设带来的脆弱性
            _CALL_MAP = {
                ("jwt_secret", "primary"): None,
                ("jwt_secret", "recovery"): {
                    "name": "jwt_secret",
                    "value": authoritative["jwt_secret"],
                },
                ("csrf_secret", "primary"): None,
                ("csrf_secret", "recovery"): {
                    "name": "csrf_secret",
                    "value": authoritative["csrf_secret"],
                },
            }
            call_state = {
                "jwt_secret": {"primary": False, "recovery": False},
                "csrf_secret": {"primary": False, "recovery": False},
            }

            def _next_phase(name: str) -> str:
                """根据已发生过的调用决定本次 find_one 应走的阶段。

                SecretService 调用契约：每个 name 必须先 primary 再 recovery，
                两个 name 之间按 jwt → csrf 顺序。本函数把这个契约显式化，
                替代原先基于全局递增计数器的奇偶判断。
                """
                state = call_state[name]
                if not state["primary"]:
                    state["primary"] = True
                    return "primary"
                if not state["recovery"]:
                    state["recovery"] = True
                    return "recovery"
                raise AssertionError(
                    f"find_one({name}) 调用次数超出契约（每 name 仅允许 2 次：primary + recovery）"
                )

            class _RacingCollection:
                """包装 system_secrets 集合，模拟并发首启的 DuplicateKeyError 场景。

                用显式 phase 映射替代奇偶计数，让"第 N 次返回 X"的契约可读、可调试。
                """

                def __init__(self, inner):
                    self._inner = inner

                async def find_one(self, filter_dict=None, projection=None):
                    name = (filter_dict or {}).get("name")
                    phase = _next_phase(name)
                    return _CALL_MAP[(name, phase)]

                async def update_one(self, *args, **kwargs):
                    update_calls["count"] += 1
                    # 生产代码捕获的是 pymongo.errors.DuplicateKeyError，测试必须用
                    # 同一具体异常类才能真实反映 catch 子句路径，避免用 Exception/RuntimeError
                    # 假阳通过（未来若改 catch 子句限定到 DuplicateKeyError，测试会立即失败）
                    from pymongo.errors import DuplicateKeyError
                    raise DuplicateKeyError("E11000 duplicate key error")

                async def insert_one(self, doc):
                    return await self._inner.insert_one(doc)

                def __getattr__(self, name):
                    return getattr(self._inner, name)

            sim_db._collections["system_secrets"] = _RacingCollection(original_collection)

            result = await ss.SecretService.ensure_secrets()

            # 验证：两次 update_one 都触发了冲突，但最终使用了 DB 权威值
            assert update_calls["count"] == 2  # jwt + csrf 各一次
            assert result["jwt_secret"] == authoritative["jwt_secret"]
            assert result["csrf_secret"] == authoritative["csrf_secret"]

            # os.environ 也应被同步为权威值
            assert os.environ["JWT_SECRET"] == authoritative["jwt_secret"]
            assert os.environ["CSRF_SECRET"] == authoritative["csrf_secret"]
        finally:
            db_mod.mongo_db = original_db
            ss._FALLBACK_FILE = original_file


# ---------------------------------------------------------------------------
# P0-4: WebSocket fail-closed 顺序
# ---------------------------------------------------------------------------


class TestWebSocketFailClosedOrder:
    """P0-4：权限异常时 accept → close(1011) 顺序。"""

    @pytest.mark.asyncio
    async def test_close_called_after_accept_on_permission_error(self, monkeypatch):
        """任务权限检查抛异常时，先 accept 再 close。"""
        call_order = []

        class _StubWebSocket:
            async def accept(self):
                call_order.append("accept")

            async def close(self, code=None, reason=None):
                call_order.append(("close", code, reason))

            @property
            def query_params(self):
                # 提供 token 让鉴权通过，进入任务查询阶段
                from app.services.auth_service import AuthService
                token = AuthService.create_access_token(sub="test_user")
                return {"token": token}

        from app.services import analysis_service as svc_mod

        # 用 monkeypatch 让 analysis_service.get_analysis_service 抛异常
        # （函数内导入路径）
        class _BoomAnalysisService:
            async def get_task_with_status_fallback(self, task_id):
                raise RuntimeError("DB down")

        monkeypatch.setattr(
            svc_mod, "get_analysis_service", lambda: _BoomAnalysisService()
        )

        from app.routers import analysis as analysis_mod
        from app.services.user_service import user_service

        # user_service 依赖 DB，让它也能找到 test_user（避免 401 提前返回）
        async def _fake_get_user_by_username(username):
            class _U:
                id = "507f1f77bcf86cd799439099"
            return _U()

        monkeypatch.setattr(
            user_service, "get_user_by_username", _fake_get_user_by_username
        )

        ws = _StubWebSocket()
        await analysis_mod.websocket_task_progress(ws, task_id="t123")

        # 验证：先 accept 再 close(1011)
        assert "accept" in call_order
        close_calls = [c for c in call_order if isinstance(c, tuple) and c[0] == "close"]
        assert close_calls, "应该至少调用一次 close"
        assert close_calls[-1][1] == 1011
        accept_idx = call_order.index("accept")
        last_close_idx = call_order.index(close_calls[-1])
        assert accept_idx < last_close_idx


# ---------------------------------------------------------------------------
# P1-1: circuit_breaker SERVICE_UNAVAILABLE 冷却倍率
# ---------------------------------------------------------------------------


class TestCircuitBreakerServiceUnavailable:
    """P1-1：SERVICE_UNAVAILABLE 错误码纳入冷却倍率表。"""

    def test_service_unavailable_has_multiplier(self):
        from app.data.processor.circuit_breaker import _ERROR_COOLDOWN_MULTIPLIERS
        from app.data.sources.base.error_codes import DataErrorCode

        assert DataErrorCode.SERVICE_UNAVAILABLE in _ERROR_COOLDOWN_MULTIPLIERS
        assert _ERROR_COOLDOWN_MULTIPLIERS[DataErrorCode.SERVICE_UNAVAILABLE] == 1.5

    def test_trip_with_service_unavailable_uses_multiplier(self):
        """连续失败触发熔断时，SERVICE_UNAVAILABLE 的冷却时间应乘以 1.5。"""
        from app.data.processor.circuit_breaker import CircuitBreaker, COOLDOWN_STEPS
        from app.data.schema.base.enums import CircuitState
        from app.data.sources.base.error_codes import DataErrorCode

        cb = CircuitBreaker()
        source, domain = "finnhub", "market_quotes"

        # 触发 FAILURE_THRESHOLD 次 SERVICE_UNAVAILABLE
        for _ in range(3):
            cb.record_failure(source, domain, error_code=DataErrorCode.SERVICE_UNAVAILABLE)

        assert cb.get_state(source, domain) == CircuitState.OPEN
        state = cb._states[(source, domain)]
        expected = min(int(COOLDOWN_STEPS[0] * 1.5), 3600)
        assert state["cooldown"] == expected

    def test_service_unavailable_same_tier_as_server_error(self):
        from app.data.processor.circuit_breaker import _ERROR_COOLDOWN_MULTIPLIERS
        from app.data.sources.base.error_codes import DataErrorCode

        # SERVICE_UNAVAILABLE 与 SERVER_ERROR 同档（上游 5xx）
        assert (
            _ERROR_COOLDOWN_MULTIPLIERS[DataErrorCode.SERVICE_UNAVAILABLE]
            == _ERROR_COOLDOWN_MULTIPLIERS[DataErrorCode.SERVER_ERROR]
        )


# ---------------------------------------------------------------------------
# L1: operation_log_middleware 死代码移除
# ---------------------------------------------------------------------------


class TestOperationLogMiddlewareNoDeadCode:
    """L1：operation_log_user fallback 已移除，仅走 JWT 解析。"""

    def _make_request(self, auth_header=""):
        from starlette.requests import Request

        scope = {
            "type": "http",
            "method": "POST",
            "path": "/api/test",
            "headers": [(b"authorization", auth_header.encode())] if auth_header else [],
            "query_string": b"",
            "client": ("127.0.0.1", 8000),
            "app": None,
        }
        return Request(scope)

    @pytest.mark.asyncio
    async def test_state_operation_log_user_ignored(self):
        """注入 request.state.operation_log_user 不应再影响结果。"""
        from app.middleware.operation_log_middleware import OperationLogMiddleware

        mw = OperationLogMiddleware.__new__(OperationLogMiddleware)
        request = self._make_request()
        # 显式注入旧的 fallback 字段
        request.state.operation_log_user = {"id": "ghost", "username": "ghost"}

        # 没有 Authorization header，应返回 None（不应返回 ghost）
        info = await mw._get_user_info(request)
        assert info is None

    @pytest.mark.asyncio
    async def test_state_user_ignored(self):
        """注入 request.state.user 也不应影响结果。"""
        from app.middleware.operation_log_middleware import OperationLogMiddleware

        mw = OperationLogMiddleware.__new__(OperationLogMiddleware)
        request = self._make_request()
        request.state.user = {"id": "u123", "username": "ghost2"}

        info = await mw._get_user_info(request)
        assert info is None


# ---------------------------------------------------------------------------
# L2: rate_limiter Redis 故障 fail-closed
# ---------------------------------------------------------------------------


class TestRateLimiterFailClosed:
    """L2：Redis 故障时 acquire 返回 False。"""

    @pytest.mark.asyncio
    async def test_redis_exception_returns_false(self, monkeypatch):
        """counter.get_count/increment 抛异常时，应 fail-closed 返回 False。"""
        from app.data.processor.rate_limiter import RateLimiter

        limiter = RateLimiter()
        limiter.configure(source="tushare", rate_per_minute=60, polite_interval_ms=0)

        # 让 counter 抛异常（模拟 Redis 连接断开）：直接替换 limiter 内的实例
        class _BoomCounter:
            async def get_count(self, key):
                raise RuntimeError("redis connection reset")

            async def increment(self, key):
                raise RuntimeError("redis connection reset")

        limiter._counters["tushare"] = _BoomCounter()

        allowed, wait = await limiter.acquire("tushare", domain="daily_quotes")
        assert allowed is False
        assert wait == 5  # 短暂等待，给 Redis 恢复时间

    @pytest.mark.asyncio
    async def test_quota_pre_check_blocks_when_full(self, inject_sim_redis):
        """配额预检：超过 rate_per_minute 时返回 False。"""
        from app.data.processor.rate_limiter import RateLimiter

        limiter = RateLimiter()
        # 设个低限便于快速触发
        limiter.configure(source="akshare", rate_per_minute=2, polite_interval_ms=0)

        # 调用三次，前两次允许，第三次被预检拒绝
        # 注意：SlidingWindowCounter 用 time.time() 作为 member，同一毫秒内会冲突
        results = []
        for _ in range(3):
            allowed, _ = await limiter.acquire("akshare", domain="daily_indicators")
            results.append(allowed)
            await asyncio.sleep(0.002)  # 错开毫秒，避免 member 冲突

        # 修复前：第三次 increment 后才会拒绝；修复后：预检阶段直接拒绝
        assert results[:2] == [True, True]
        assert results[2] is False

    @pytest.mark.asyncio
    async def test_pre_check_does_not_consume_quota(self, monkeypatch):
        """关键修复点：被拒绝的请求不应消耗配额。

        场景：rate=2，前两次通过；第三次调用 5 次，每次都应被拒绝且不递增。
        之后仍允许通过 0 次（配额已被前两次耗尽）。

        注意：原测试用 inject_sim_redis，但 SimulatedRedis 不支持 eval(Lua)，
        try_increment 会降级到 _memory_counters；而 get_count 仍走 sim_redis，
        两者数据源不一致 → 测试结果假阴。
        修复：让 get_redis 返回 None，强制两条路径都走 _memory_counters。
        """
        from app.data.storage.redis import client as redis_client_mod
        from app.data.processor.rate_limiter import RateLimiter
        from app.data.storage.redis.counters import _memory_counters

        # 统一走内存降级路径，保证写入与读取同源
        monkeypatch.setattr(redis_client_mod, "get_redis", lambda: None)
        _memory_counters.pop("ratelimit:tushare", None)

        limiter = RateLimiter()
        limiter.configure(source="tushare", rate_per_minute=2, polite_interval_ms=0)

        # 两次通过（错开毫秒避免 time.time() 同值）
        await limiter.acquire("tushare", domain="daily_quotes")
        await asyncio.sleep(0.002)
        await limiter.acquire("tushare", domain="daily_quotes")

        # 被拒绝 5 次（原子 try_increment 在 limit 已满时直接返回 False，不写入）
        for _ in range(5):
            allowed, _ = await limiter.acquire("tushare", domain="daily_quotes")
            assert allowed is False

        # 内存计数仍应只有 2（修复前会是 7）
        from app.data.storage.redis.counters import SlidingWindowCounter
        counter = SlidingWindowCounter(window_seconds=60)
        actual = await counter.get_count("ratelimit:tushare")
        assert actual == 2

        # 清理避免污染后续测试
        _memory_counters.pop("ratelimit:tushare", None)
