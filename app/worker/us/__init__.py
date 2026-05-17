"""
美股 Worker 入口（按需缓存模式）

美股数据采用按需获取+缓存模式，不使用定时同步任务。
us_cache_service.py 提供按需缓存服务。
"""

from app.worker.us.us_cache_service import USCacheService, get_us_cache_service

__all__ = ["USCacheService", "get_us_cache_service"]
