"""Redis 客户端封装 — 桥接 app/core/database.py。"""


_redis_client = None


def get_redis():
    """获取 Redis 异步客户端。"""
    global _redis_client
    if _redis_client is None:
        from app.core.database import get_redis_client
        _redis_client = get_redis_client()
    return _redis_client


def reset_client():
    """重置客户端引用（测试用）。"""
    global _redis_client
    _redis_client = None
