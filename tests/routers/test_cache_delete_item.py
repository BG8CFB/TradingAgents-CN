"""
测试 DELETE /api/cache/items/{key} 端点

按 CLAUDE.md 规则：
- 使用 conda 环境 tradingagents
- 不使用 mock
- 真实调用 FastAPI 应用（authed_client fixture）
- Redis 不可用时优雅降级；可用时验证真实删除
"""

import socket

import pytest

from app.data.storage.cache.memory_cache import TTLCache
from app.data.storage.redis.client import reset_client
from app.routers.cache import set_memory_cache


def _check_redis_available() -> bool:
    """检测 Redis 是否可用"""
    try:
        s = socket.create_connection(("localhost", 6379), timeout=1)
        s.close()
        return True
    except OSError:
        return False


@pytest.fixture(autouse=True)
def _isolate_redis_client():
    """每个测试前后重置 redis 客户端缓存，避免跨用例污染。"""
    reset_client()
    yield
    reset_client()


@pytest.mark.asyncio
async def test_delete_cache_item_from_memory(authed_client):
    """验证 DELETE 端点删除内存 TTLCache 中的项"""
    cache = TTLCache(default_ttl=60)
    set_memory_cache(cache)
    try:
        cache.set("test:memory:key", {"foo": "bar"}, ttl=60)
        assert cache.get("test:memory:key") is not None

        resp = await authed_client.delete("/api/cache/items/test:memory:key")
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["data"]["key"] == "test:memory:key"
        assert body["data"]["existed"] is True
        assert body["data"]["memory_deleted"] is True
        assert cache.get("test:memory:key") is None
    finally:
        set_memory_cache(None)


@pytest.mark.asyncio
async def test_delete_cache_item_nonexistent(authed_client):
    """验证删除不存在的键返回 existed=False 而非 404"""
    cache = TTLCache(default_ttl=60)
    set_memory_cache(cache)
    try:
        resp = await authed_client.delete("/api/cache/items/definitely:nonexistent:key")
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["data"]["existed"] is False
    finally:
        set_memory_cache(None)


@pytest.mark.asyncio
async def test_delete_cache_item_with_slash_in_key(authed_client):
    """验证含斜杠的 key 通过 path 参数正确传递"""
    cache = TTLCache(default_ttl=60)
    set_memory_cache(cache)
    try:
        complex_key = "foreign_stock:US/AAPL/2024-01-01"
        cache.set(complex_key, "data", ttl=60)

        # key 使用 {key:path} 转换器，可包含 /
        resp = await authed_client.delete(f"/api/cache/items/{complex_key}")
        assert resp.status_code == 200
        body = resp.json()
        assert body["data"]["key"] == complex_key
        assert body["data"]["existed"] is True
        assert cache.get(complex_key) is None
    finally:
        set_memory_cache(None)


@pytest.mark.asyncio
async def test_delete_cache_item_requires_admin(user_client):
    """验证 DELETE 端点要求管理员权限。

    使用真实普通用户 token（user_client fixture）：get_current_user 走真实流程，
    require_admin 校验 is_admin=False，应返回 403。不使用 dependency_overrides。
    """
    resp = await user_client.delete("/api/cache/items/any:key")
    assert resp.status_code == 403


@pytest.mark.asyncio
@pytest.mark.skipif(
    not _check_redis_available(),
    reason="Redis 不可用",
)
async def test_delete_cache_item_from_redis(authed_client):
    """Redis 可用时验证从 Redis 真实删除。

    手动注入真实 Redis 客户端到 redis.client._redis_client（不依赖 lifespan）。
    """
    import os
    import redis.asyncio as redis_async
    from app.data.storage.redis import client as redis_client_module

    password = os.environ.get("REDIS_PASSWORD", "tradingagents123")
    redis = redis_async.Redis(
        host=os.environ.get("REDIS_HOST", "localhost"),
        port=int(os.environ.get("REDIS_PORT", "6379")),
        password=password,
        decode_responses=True,
    )

    # 测试连通性
    try:
        await redis.ping()
    except Exception as e:
        pytest.skip(f"Redis 无法连接: {e}")

    # 注入到全局，让 cache.py 的 get_redis() 拿到此实例
    original = redis_client_module._redis_client
    redis_client_module._redis_client = redis

    test_key = "test:redis:delete:item:key"
    try:
        await redis.set(test_key, "value", ex=60)
        assert await redis.exists(test_key) == 1

        resp = await authed_client.delete(f"/api/cache/items/{test_key}")
        assert resp.status_code == 200
        body = resp.json()
        assert body["data"]["existed"] is True
        assert body["data"]["redis_deleted"] is True

        assert await redis.exists(test_key) == 0
    finally:
        # 清理 Redis 残留
        try:
            await redis.delete(test_key)
        except Exception:
            pass
        # 恢复全局状态
        redis_client_module._redis_client = original
        try:
            await redis.aclose()
        except Exception:
            pass


def test_ttl_cache_invalidate_returns_bool():
    """验证 TTLCache.invalidate 返回值能反映键是否存在（消除竞态修复）"""
    cache = TTLCache(default_ttl=60)
    cache.set("exists:key", "v", ttl=60)

    assert cache.invalidate("exists:key") is True     # 存在 → True
    assert cache.invalidate("exists:key") is False    # 再次删除（不存在）→ False
    assert cache.invalidate("never:existed") is False  # 从未存在 → False
