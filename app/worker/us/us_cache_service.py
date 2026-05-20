"""
美股按需缓存服务

通过 sources/us/ 编排模块（Provider → Adapter → Schema → MongoDB）获取数据。
"""

import logging
import threading
from typing import Optional

from app.worker.base_sync_service import ForeignMarketCacheService

logger = logging.getLogger(__name__)


class USCacheService(ForeignMarketCacheService):
    """美股按需缓存服务"""

    market = "US"
    _log_label = "美股缓存"
    orchestrator_map = {
        "yfinance": ("app.data.sources.us.yfinance_us.orchestrator", "YFinanceUSOrchestrator",
                      "app.data.sources.us.yfinance_us", "get_yfinance_us_adapter"),
        "finnhub": ("app.data.sources.us.finnhub_us.orchestrator", "FinnhubUSOrchestrator",
                     "app.data.sources.us.finnhub_us", "get_finnhub_us_adapter"),
    }

    def normalize_code(self, code: str) -> str:
        return code.upper()


_us_cache_service: Optional[USCacheService] = None
_us_cache_service_lock = threading.Lock()


def get_us_cache_service() -> USCacheService:
    """获取美股缓存服务实例（线程安全单例）"""
    global _us_cache_service
    if _us_cache_service is not None:
        return _us_cache_service
    with _us_cache_service_lock:
        if _us_cache_service is None:
            _us_cache_service = USCacheService()
    return _us_cache_service
