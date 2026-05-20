"""
港股按需缓存服务

通过 sources/hk/ 编排模块（Provider → Adapter → Schema → MongoDB）获取数据。
"""

import logging
import threading
from typing import Optional

from app.worker.base_sync_service import ForeignMarketCacheService

logger = logging.getLogger(__name__)


class HKCacheService(ForeignMarketCacheService):
    """港股按需缓存服务"""

    market = "HK"
    _log_label = "港股缓存"
    orchestrator_map = {
        "akshare": ("app.data.sources.hk.akshare_hk.orchestrator", "AKShareHKOrchestrator",
                     "app.data.sources.hk.akshare_hk", "get_akshare_hk_adapter"),
        "yfinance": ("app.data.sources.hk.yfinance_hk.orchestrator", "YFinanceHKOrchestrator",
                      "app.data.sources.hk.yfinance_hk", "get_yfinance_hk_adapter"),
    }

    def normalize_code(self, code: str) -> str:
        return code.lstrip('0').zfill(5)


_hk_cache_service: Optional[HKCacheService] = None
_hk_cache_service_lock = threading.Lock()


def get_hk_cache_service() -> HKCacheService:
    """获取港股缓存服务实例（线程安全单例）"""
    global _hk_cache_service
    if _hk_cache_service is not None:
        return _hk_cache_service
    with _hk_cache_service_lock:
        if _hk_cache_service is None:
            _hk_cache_service = HKCacheService()
    return _hk_cache_service
