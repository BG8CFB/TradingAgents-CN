"""Redis 客户端封装 — 桥接 app/core/database.py。"""


_redis_client = None


def get_redis():
    """获取 Redis 异步客户端。

    若底层数据库尚未初始化（如应用未启动 lifespan），返回 None 而非抛异常，
    让调用方能以 ``if redis:`` 形式优雅降级。
    """
    global _redis_client
    if _redis_client is None:
        try:
            from app.core.database import get_redis_client
            _redis_client = get_redis_client()
        except RuntimeError:
            return None
    return _redis_client


def reset_client():
    """重置客户端引用（测试用）。"""
    global _redis_client
    _redis_client = None
