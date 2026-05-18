"""
港股 Worker 入口

- 按需缓存：hk_cache_service.py（保留，用户分析时触发预热）
- 全量同步：hk_sync_service.py（默认关闭，用户通过 .env 启用）
"""

from app.worker.hk.hk_cache_service import HKCacheService, get_hk_cache_service
from app.worker.hk.hk_sync_service import (
    HKSyncService,
    get_hk_sync_service,
    run_hk_basic_info_sync,
    run_hk_daily_quotes_sync,
    run_hk_status_check,
)

__all__ = [
    "HKCacheService", "get_hk_cache_service",
    "HKSyncService", "get_hk_sync_service",
    "run_hk_basic_info_sync", "run_hk_daily_quotes_sync", "run_hk_status_check",
]
