"""RateLimiter Token 感知分桶 + 日配额测试（真实 Redis）。

覆盖 Phase 2 改造点：

1. 同一 Token 的两个数据源共享分钟级配额桶（Tushare 三市场同账号积分共享）
2. 无 Token 的源维持 ``ratelimit:{source}`` 独立桶
3. ``rate_per_day`` 日配额：Redis INCR 日计数，超额拒绝并给出等待时间

全部走真实 Redis（docker 实例）；测试结束清理自己写入的键。
"""

import hashlib
from datetime import datetime

import pytest
import pytest_asyncio
import redis.asyncio as aioredis

from app.core.config import settings
from app.data.processor.rate_limiter import RateLimiter, _bucket_key


@pytest_asyncio.fixture
async def real_redis(monkeypatch):
    """连接真实 Redis 并注入到 storage.client.get_redis。

    注入的是真实客户端（非模拟），仅绕过 lifespan 初始化。
    """
    from app.data.storage.redis import client as redis_client_mod

    client = aioredis.from_url(
        settings.REDIS_URL,
        decode_responses=True,
        socket_connect_timeout=5,
        socket_timeout=10,
    )
    await client.ping()
    monkeypatch.setattr(redis_client_mod, "get_redis", lambda: client)
    yield client
    await client.aclose()


class TestBucketKey:
    """_bucket_key 分桶键格式。"""

    def test_with_token_uses_hash_only(self):
        token = "secret-token-abc"
        digest = hashlib.sha256(token.encode()).hexdigest()[:8]
        assert _bucket_key("tushare", token) == f"ratelimit:{digest}"
        assert _bucket_key("tushare_hk", token) == f"ratelimit:{digest}"
        assert _bucket_key("tushare_us", token) == f"ratelimit:{digest}"

    def test_without_token_uses_source(self):
        assert _bucket_key("akshare", None) == "ratelimit:akshare"

    def test_empty_token_treated_as_absent(self):
        assert _bucket_key("akshare", "") == "ratelimit:akshare"


class TestTokenSharedBucket:
    """同一 Token 跨源共享分钟级配额。"""

    @pytest.mark.asyncio
    async def test_same_token_two_sources_share_quota(self, real_redis):
        token = "test-token-shared-bucket"
        digest = hashlib.sha256(token.encode()).hexdigest()[:8]
        bucket = f"ratelimit:{digest}"
        await real_redis.delete(bucket)

        limiter = RateLimiter()
        limiter.configure("tushare_test_a", rate_per_minute=3, polite_interval_ms=0)
        limiter.configure("tushare_test_b", rate_per_minute=3, polite_interval_ms=0)

        try:
            # 源 A 消耗 3 次配额
            for _ in range(3):
                ok, _ = await limiter.acquire("tushare_test_a", token=token)
                assert ok is True

            # 同 Token 的源 B 第 4 次应被拒（共享桶已满）
            ok, wait = await limiter.acquire("tushare_test_b", token=token)
            assert ok is False
            assert wait > 0

            # Redis 中确实只有一个桶
            count = await real_redis.zcard(bucket)
            assert count == 3
        finally:
            await real_redis.delete(bucket)

    @pytest.mark.asyncio
    async def test_no_token_sources_keep_independent_buckets(self, real_redis):
        # 不注入 Token（源不在 _DS_ENV_MAP 中，DB 也不会配置）→ 无 Token 路径
        limiter = RateLimiter()
        limiter.configure("notoken_src_x", rate_per_minute=2, polite_interval_ms=0)
        limiter.configure("notoken_src_y", rate_per_minute=2, polite_interval_ms=0)

        for key in ("ratelimit:notoken_src_x", "ratelimit:notoken_src_y"):
            await real_redis.delete(key)

        try:
            ok1, _ = await limiter.acquire("notoken_src_x")
            ok2, _ = await limiter.acquire("notoken_src_x")
            assert ok1 and ok2
            ok3, _ = await limiter.acquire("notoken_src_x")
            assert ok3 is False

            # 另一个源不受影响（独立桶）
            ok_other, _ = await limiter.acquire("notoken_src_y")
            assert ok_other is True
        finally:
            await real_redis.delete("ratelimit:notoken_src_x")
            await real_redis.delete("ratelimit:notoken_src_y")


class TestRatePerDay:
    """rate_per_day 日配额 — Redis INCR 日计数、超额拒绝。"""

    @pytest.mark.asyncio
    async def test_daily_quota_rejects_after_limit(self, real_redis):
        token = "test-token-daily-quota"
        digest = hashlib.sha256(token.encode()).hexdigest()[:8]
        bucket = f"ratelimit:{digest}"
        day = datetime.now().strftime("%Y%m%d")
        daily_key = f"ratelimit_day:{bucket}:{day}"
        await real_redis.delete(bucket)
        await real_redis.delete(daily_key)

        limiter = RateLimiter()
        limiter.configure(
            "tushare_test_day",
            rate_per_minute=100,
            rate_per_day=2,
            polite_interval_ms=0,
        )

        try:
            ok1, _ = await limiter.acquire("tushare_test_day", token=token)
            ok2, _ = await limiter.acquire("tushare_test_day", token=token)
            assert ok1 and ok2

            # 第 3 次：分钟窗口未满但日配额触顶 → 拒绝
            ok3, wait = await limiter.acquire("tushare_test_day", token=token)
            assert ok3 is False
            assert wait > 0

            # Redis 日计数 key 存在且值为 3（INCR 先占额再判断）
            count = await real_redis.get(daily_key)
            assert int(count) == 3
            # TTL 已设置（48h 窗口）
            ttl = await real_redis.ttl(daily_key)
            assert 0 < ttl <= 48 * 3600
        finally:
            await real_redis.delete(bucket)
            await real_redis.delete(daily_key)
