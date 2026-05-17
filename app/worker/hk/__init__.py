"""
港股 Worker 入口（按需缓存模式）

港股数据采用按需获取+缓存模式，不使用定时同步任务。
hk_cache_service.py 提供按需缓存服务。
"""

from app.worker.hk.hk_cache_service import HKCacheService, get_hk_cache_service

__all__ = ["HKCacheService", "get_hk_cache_service"]
