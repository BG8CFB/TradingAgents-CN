"""Redis 客户端封装 — 桥接 app/core/database.py。"""

import logging

logger = logging.getLogger(__name__)

_redis_client = None
_unavailable_logged = False


def get_redis():
    """获取 Redis 异步客户端。

    若底层数据库尚未初始化（如应用未启动 lifespan），返回 None 而非抛异常，
    让调用方能以 ``if redis:`` 形式优雅降级；首次降级记 WARNING 保证可感知
    （此前的静默 None 会让 Redis 长期不可用而无任何日志线索）。
    """
    global _redis_client, _unavailable_logged
    if _redis_client is None:
        try:
            from app.core.database import get_redis_client
            _redis_client = get_redis_client()
        except RuntimeError as e:
            if not _unavailable_logged:
                logger.warning(f"Redis 不可用，进入降级模式（本进程只提示一次）: {e}")
                _unavailable_logged = True
            return None
    return _redis_client


def reset_client():
    """重置客户端引用（测试用）。"""
    global _redis_client
    _redis_client = None
