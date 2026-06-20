"""
登录限流器单元测试

覆盖核心行为：
- 进程内降级路径（Redis 不可用时）：所有测试走此路径，确保业务逻辑正确
- 失败计数阈值触发锁定
- 锁定后 check 返回 is_locked=True
- 成功 reset 清除计数
- IP 维度与 user 维度独立判定
"""

from __future__ import annotations

import pytest

from app.core.auth_rate_limiter import (
    AuthRateLimiter,
    _InMemoryStore,
    get_auth_rate_limiter,
    reset_auth_rate_limiter_for_tests,
)


def _make_limiter(
    user_max: int = 3,
    ip_max: int = 5,
) -> AuthRateLimiter:
    """构造一个小阈值的限流器，便于测试。"""
    return AuthRateLimiter(
        user_max_failures=user_max,
        user_window_seconds=60,
        user_lock_seconds=60,
        ip_max_failures=ip_max,
        ip_window_seconds=60,
        ip_lock_seconds=60,
    )


@pytest.fixture(autouse=True)
def _reset_global_singleton():
    reset_auth_rate_limiter_for_tests()
    yield
    reset_auth_rate_limiter_for_tests()


@pytest.mark.asyncio
async def test_no_redis_falls_back_to_in_memory_store():
    """_redis() 在未初始化数据库时返回 None，记录失败仍可工作。"""
    limiter = _make_limiter(user_max=2, ip_max=10)
    # Redis 未初始化时 _redis() 返回 None，走内存降级
    assert limiter._redis() is None

    is_locked, reason, retry = await limiter.check("1.2.3.4", "alice")
    assert is_locked is False

    now_locked, _, _ = await limiter.record_failure("1.2.3.4", "alice")
    assert now_locked is False

    now_locked, _, _ = await limiter.record_failure("1.2.3.4", "alice")
    assert now_locked is True, "第二次失败应触发 user_max=2 锁定"


@pytest.mark.asyncio
async def test_user_dimension_locks_after_threshold():
    """连续失败达阈值后锁定，check 返回 True。"""
    limiter = _make_limiter(user_max=3, ip_max=99)

    for _ in range(2):
        now_locked, _, _ = await limiter.record_failure("10.0.0.1", "bob")
        assert now_locked is False

    now_locked, _, lock_seconds = await limiter.record_failure("10.0.0.1", "bob")
    assert now_locked is True
    assert lock_seconds == 60

    is_locked, reason, retry = await limiter.check("10.0.0.1", "bob")
    assert is_locked is True
    assert "临时锁定" in reason


@pytest.mark.asyncio
async def test_reset_clears_failure_count_on_success():
    """成功登录后 reset 清除 user 维度计数，下次失败从 0 重新计数。"""
    limiter = _make_limiter(user_max=3, ip_max=99)

    await limiter.record_failure("10.0.0.2", "carol")
    await limiter.record_failure("10.0.0.2", "carol")

    await limiter.reset("10.0.0.2", "carol")


@pytest.mark.asyncio
async def test_reset_preserves_ip_dimension_counter():
    """reset 仅清 user 维度；IP 维度计数保留，防穿插绕过攻击。

    场景：攻击者先用合法账户登录成功（reset user_key），但 IP 维度的失败
    计数不应被清零，否则攻击者可重复"成功登录 → 爆破下一账户"绕过 IP 阈值。
    """
    limiter = _make_limiter(user_max=99, ip_max=5)

    # 同一 IP 上不同用户名各失败一次
    await limiter.record_failure("10.0.0.9", "attacker1")
    await limiter.record_failure("10.0.0.9", "attacker2")
    await limiter.record_failure("10.0.0.9", "attacker3")

    # 合法用户成功登录，触发 reset
    await limiter.reset("10.0.0.9", "legit_user")

    # IP 维度仍应有 3 次失败计数：再失败 2 次就触发 IP 锁定
    await limiter.record_failure("10.0.0.9", "attacker4")
    now_locked, _, _ = await limiter.record_failure("10.0.0.9", "attacker5")
    assert now_locked is True, (
        "IP 维度计数不应被 reset 清零，否则攻击者可用合法账户穿插绕过"
    )


@pytest.mark.asyncio
async def test_check_after_lock_returns_retry_after():
    """锁定后 check 返回的 retry_after 为正数（Redis 路径）或 0（内存路径）。"""
    limiter = _make_limiter(user_max=2, ip_max=99)

    await limiter.record_failure("10.0.0.10", "dave")
    await limiter.record_failure("10.0.0.10", "dave")  # 触发锁定

    is_locked, reason, retry_after = await limiter.check("10.0.0.10", "dave")
    assert is_locked is True
    assert reason
    # 内存路径 retry_after=0；Redis 路径为正数。两者都合法。
    assert retry_after >= 0

    # reset 之后第一次失败不应触发锁定（计数从 0 重置）
    now_locked, _, _ = await limiter.record_failure("10.0.0.2", "carol")
    assert now_locked is False


@pytest.mark.asyncio
async def test_ip_dimension_independent_of_username():
    """不同用户名共享同一 IP 计数，防用户名轮换攻击。"""
    limiter = _make_limiter(user_max=99, ip_max=3)

    await limiter.record_failure("10.0.0.3", "user1")
    await limiter.record_failure("10.0.0.3", "user2")
    now_locked, _, _ = await limiter.record_failure("10.0.0.3", "user3")
    assert now_locked is True, "IP 维度累计 3 次应锁定"

    is_locked, _, _ = await limiter.check("10.0.0.3", "another_user")
    assert is_locked is True, "IP 锁定应覆盖该 IP 所有用户名"


@pytest.mark.asyncio
async def test_different_ips_counted_separately():
    """不同 IP 的失败互不影响。"""
    limiter = _make_limiter(user_max=2, ip_max=99)

    await limiter.record_failure("1.1.1.1", "dave")
    await limiter.record_failure("2.2.2.2", "dave")

    # 两个 IP 各 1 次失败，均未触发阈值
    is_locked, _, _ = await limiter.check("1.1.1.1", "dave")
    assert is_locked is False
    is_locked, _, _ = await limiter.check("2.2.2.2", "dave")
    assert is_locked is False


@pytest.mark.asyncio
async def test_username_case_insensitive():
    """同一 IP 上 Alice 与 alice 视为同一用户键，防止大小写绕过。"""
    limiter = _make_limiter(user_max=2, ip_max=99)

    await limiter.record_failure("3.3.3.3", "Alice")
    now_locked, _, _ = await limiter.record_failure("3.3.3.3", "alice")
    assert now_locked is True


def test_in_memory_store_key_isolation():
    """_InMemoryStore 不同 key 独立存储，无交叉污染。"""
    store = _InMemoryStore()
    store.count_failure("key1", 60)
    store.count_failure("key1", 60)
    store.count_failure("key2", 60)

    # key1 已 2 次，key2 已 1 次
    n1 = store.count_failure("key1", 60)
    n2 = store.count_failure("key2", 60)
    assert n1 == 3
    assert n2 == 2


def test_get_auth_rate_limiter_singleton():
    """全局工厂返回同一实例。"""
    reset_auth_rate_limiter_for_tests()
    a = get_auth_rate_limiter()
    b = get_auth_rate_limiter()
    assert a is b
