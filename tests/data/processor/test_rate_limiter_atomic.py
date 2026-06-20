"""RateLimiter 原子性并发回归测试（P0-22）。

背景：
    原实现 ``RateLimiter.acquire`` 用 ``get_count`` 预检 + ``increment`` 两步，
    高并发下多个协程会同时通过预检（看到 count < limit）后递增，导致实际通过数
    超过 ``rate_per_minute``。
    修复后改用 ``SlidingWindowCounter.try_increment``（Redis Lua 原子脚本，
    内存降级用 ``threading.Lock`` 保证），单次操作完成"清理 + 检查 + 递增"。

测试策略：
    - 100 个协程并发 acquire，限制 rate_per_minute=10
    - 断言：通过数 ≤ 10（不允许超量）
    - 断言：被拒绝的请求不消耗配额（Redis/Memory 计数仍为 10）
    - 覆盖 Redis 路径与内存降级路径
"""

import asyncio

import pytest


# ── 内存降级路径（默认 sim_redis 不注入，让 try_increment 走内存兜底）────────


class TestRateLimiterAtomicMemoryFallback:
    """内存降级路径下的原子性（threading.Lock 保护）。"""

    @pytest.mark.asyncio
    async def test_concurrent_acquire_does_not_exceed_limit(self, monkeypatch):
        """100 并发 → 限制 10，断言通过数 ≤ 10。"""
        from app.data.processor.rate_limiter import RateLimiter
        from app.data.storage.redis import client as redis_client_mod
        from app.data.storage.redis.counters import _memory_counters

        # 强制走内存降级：get_redis 返回 None
        monkeypatch.setattr(redis_client_mod, "get_redis", lambda: None)
        # 清理残留计数
        _memory_counters.pop("ratelimit:test_atomic", None)

        limiter = RateLimiter()
        limiter.configure(
            source="test_atomic",
            rate_per_minute=10,
            polite_interval_ms=0,
        )

        results = await asyncio.gather(*[
            limiter.acquire("test_atomic", domain="test")
            for _ in range(100)
        ])

        allowed_count = sum(1 for ok, _ in results if ok)
        # 关键断言：通过数绝不超过 10
        assert allowed_count <= 10, (
            f"并发通过 {allowed_count} > 10，原子性失败"
        )
        # 也至少应该通过 1 个（limit > 0 时）
        assert allowed_count >= 1, "至少应允许首次请求通过"

        # 清理
        _memory_counters.pop("ratelimit:test_atomic", None)

    @pytest.mark.asyncio
    async def test_rejected_acquire_does_not_consume_quota(self, monkeypatch):
        """被拒绝的请求不写入计数器，不会污染后续窗口。"""
        from app.data.processor.rate_limiter import RateLimiter
        from app.data.storage.redis import client as redis_client_mod
        from app.data.storage.redis.counters import (
            SlidingWindowCounter,
            _memory_counters,
        )

        monkeypatch.setattr(redis_client_mod, "get_redis", lambda: None)
        _memory_counters.pop("ratelimit:test_quota", None)

        limiter = RateLimiter()
        limiter.configure(
            source="test_quota",
            rate_per_minute=2,
            polite_interval_ms=0,
        )

        # 串行：2 次允许，第 3 次拒绝
        ok1, _ = await limiter.acquire("test_quota", domain="test")
        await asyncio.sleep(0.002)  # 错开 ms
        ok2, _ = await limiter.acquire("test_quota", domain="test")
        await asyncio.sleep(0.002)
        ok3, _ = await limiter.acquire("test_quota", domain="test")

        assert ok1 and ok2
        assert not ok3

        # 内存计数应只有 2（被拒绝的第 3 次不写入）
        counter = SlidingWindowCounter(window_seconds=60)
        count = await counter.get_count("ratelimit:test_quota")
        assert count == 2, f"配额应保持 2，实际 {count}（说明被拒请求污染了计数）"

        _memory_counters.pop("ratelimit:test_quota", None)


# ── Redis 路径（用 SimulatedRedis 注入）────────────────────────────


class TestRateLimiterAtomicRedisPath:
    """Redis 路径下的原子性（Lua 脚本在真实 Redis 上原子，
    SimulatedRedis 上虽无 Lua 但 try_increment 内存降级路径保证原子）。"""

    @pytest.mark.asyncio
    async def test_concurrent_acquire_with_sim_redis(self, sim_redis, monkeypatch):
        """注入 SimulatedRedis 后并发 acquire 不超量。"""
        from app.data.storage.redis import client as redis_client_mod
        from app.data.processor.rate_limiter import RateLimiter
        from app.data.storage.redis.counters import _memory_counters

        # 让 try_increment 路径能拿到 sim_redis（真实 redis-py 调用）
        # 注意：SimulatedRedis 不支持 eval(Lua)，会抛异常 → 降级到内存路径
        # 内存路径用 _memory_counters_lock 保证原子性
        monkeypatch.setattr(redis_client_mod, "get_redis", lambda: sim_redis)
        _memory_counters.pop("ratelimit:test_atomic_redis", None)

        limiter = RateLimiter()
        limiter.configure(
            source="test_atomic_redis",
            rate_per_minute=10,
            polite_interval_ms=0,
        )

        results = await asyncio.gather(*[
            limiter.acquire("test_atomic_redis", domain="test")
            for _ in range(100)
        ])

        allowed_count = sum(1 for ok, _ in results if ok)
        assert allowed_count <= 10, (
            f"Redis 路径并发通过 {allowed_count} > 10，原子性失败"
        )
        assert allowed_count >= 1

        _memory_counters.pop("ratelimit:test_atomic_redis", None)


# ── try_increment 直接单测 ─────────────────────────────


class TestTryIncrementContract:
    """直接验证 SlidingWindowCounter.try_increment 接口契约。"""

    @pytest.mark.asyncio
    async def test_try_increment_returns_allowed_and_retry(self, monkeypatch):
        """limit=2 时：第 1/2 次 allowed=True，第 3 次 allowed=False。"""
        from app.data.storage.redis import client as redis_client_mod
        from app.data.storage.redis.counters import (
            SlidingWindowCounter,
            _memory_counters,
        )

        monkeypatch.setattr(redis_client_mod, "get_redis", lambda: None)
        _memory_counters.pop("rl:test_contract", None)

        counter = SlidingWindowCounter(window_seconds=60)

        ok1, retry1 = await counter.try_increment("rl:test_contract", 2)
        assert ok1 is True
        assert retry1 == 0

        await asyncio.sleep(0.002)
        ok2, retry2 = await counter.try_increment("rl:test_contract", 2)
        assert ok2 is True
        assert retry2 == 0

        await asyncio.sleep(0.002)
        ok3, retry3 = await counter.try_increment("rl:test_contract", 2)
        # 关键契约：超限时返回 False 且不写入
        assert ok3 is False
        assert retry3 > 0  # 给出建议等待时间

        # 内存中应只有 2 条记录（第 3 次被拒未写入）
        assert len(_memory_counters["rl:test_contract"]) == 2

        _memory_counters.pop("rl:test_contract", None)
