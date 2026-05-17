"""
港股按需缓存服务

通过 sources/hk/ 编排模块（Provider → Adapter → Schema → MongoDB）获取数据。
"""

import logging
import threading
from datetime import timedelta
from typing import Any, Dict, List, Optional, Set

from app.core.database import get_mongo_db
from app.data.config import get_enabled_sources
from app.data.schema.collections import get_collection_name
from app.utils.timezone import now_config_tz

logger = logging.getLogger(__name__)

# 默认缓存时长（小时）
DEFAULT_CACHE_HOURS = 24


class HKCacheService:
    """港股按需缓存服务"""

    def __init__(self):
        self._basic_info_collection = get_collection_name("HK", "basic_info")
        self._daily_quotes_collection = get_collection_name("HK", "daily_quotes")

    def _get_db(self):
        return get_mongo_db()

    async def _count_cached_symbols(self) -> int:
        collection = self._get_db()[self._basic_info_collection]
        symbols: Set[str] = set()
        for field in ("symbol", "code"):
            try:
                values = await collection.distinct(field)
            except Exception:
                values = []
            symbols.update(str(value).strip() for value in values if value)
        return len(symbols)

    def _get_orchestrators(self) -> List:
        """按优先级获取可用的编排模块"""
        orchestrator_map = {
            "akshare": ("app.data.sources.hk.akshare_hk.orchestrator", "AKShareHKOrchestrator",
                         "app.data.sources.hk.akshare_hk", "get_akshare_hk_adapter"),
            "yfinance": ("app.data.sources.hk.yfinance_hk.orchestrator", "YFinanceHKOrchestrator",
                          "app.data.sources.hk.yfinance_hk", "get_yfinance_hk_adapter"),
        }
        sources = get_enabled_sources("HK")
        result = []
        for src in sources:
            if src in orchestrator_map:
                result.append(orchestrator_map[src])
        return result

    def _get_orchestrator_instance(self, orch_info):
        """懒加载编排模块实例"""
        orch_module, orch_class, adapter_module, adapter_factory = orch_info
        import importlib
        mod = importlib.import_module(adapter_module)
        adapter = getattr(mod, adapter_factory)()
        orch_mod = importlib.import_module(orch_module)
        return getattr(orch_mod, orch_class)(adapter)

    async def get_stock_info(self, stock_code: str) -> Optional[Dict[str, Any]]:
        """获取港股基础信息（带缓存）"""
        normalized_code = stock_code.lstrip('0').zfill(5)

        # 1. 先查缓存
        cached = await self._get_cached_info(normalized_code)
        if cached:
            return cached

        # 2. 缓存未命中，通过编排模块预热
        for orch_info in self._get_orchestrators():
            try:
                orch = self._get_orchestrator_instance(orch_info)
                success = await orch.warm_stock_info(normalized_code)
                if success:
                    cached = await self._get_cached_info(normalized_code)
                    if cached:
                        return cached
            except Exception as e:
                logger.warning(f"⚠️ [港股缓存] {stock_code} 预热失败: {e}")
                continue

        logger.warning(f"⚠️ [港股缓存] {stock_code} 所有数据源均失败")
        return None

    async def refresh_cache(self, stock_code: str) -> Optional[Dict[str, Any]]:
        """强制刷新缓存"""
        normalized_code = stock_code.lstrip('0').zfill(5)
        for orch_info in self._get_orchestrators():
            try:
                orch = self._get_orchestrator_instance(orch_info)
                await orch.warm_stock_info(normalized_code)
            except Exception as e:
                logger.warning(f"⚠️ [港股缓存] 刷新 {stock_code} 失败: {e}")

        return await self._get_cached_info(normalized_code)

    async def get_cache_stats(self) -> Dict[str, Any]:
        db = self._get_db()
        collection = db[self._basic_info_collection]
        expire_before = now_config_tz() - timedelta(hours=DEFAULT_CACHE_HOURS)

        total_documents = await collection.count_documents({})
        valid_documents = await collection.count_documents({"updated_at": {"$gte": expire_before}})
        latest_doc = await collection.find_one({}, sort=[("updated_at", -1)])

        return {
            "market": "HK",
            "cache_hours": DEFAULT_CACHE_HOURS,
            "available_sources": get_enabled_sources("HK"),
            "collection": self._basic_info_collection,
            "cached_symbols": await self._count_cached_symbols(),
            "total_documents": total_documents,
            "valid_documents": valid_documents,
            "expired_documents": max(total_documents - valid_documents, 0),
            "last_updated": latest_doc.get("updated_at") if latest_doc else None,
            "latest_symbol": (latest_doc or {}).get("symbol") or (latest_doc or {}).get("code"),
        }

    async def clear_expired_cache(self) -> Dict[str, Any]:
        expire_before = now_config_tz() - timedelta(hours=DEFAULT_CACHE_HOURS)
        result = await self._get_db()[self._basic_info_collection].delete_many(
            {"updated_at": {"$lt": expire_before}}
        )
        return {
            "market": "HK",
            "collection": self._basic_info_collection,
            "deleted_count": result.deleted_count,
            "expire_before": expire_before,
        }

    async def _get_cached_info(self, code: str) -> Optional[Dict[str, Any]]:
        """从 MongoDB 缓存读取"""
        collection = self._get_db()[self._basic_info_collection]
        expire_before = now_config_tz() - timedelta(hours=DEFAULT_CACHE_HOURS)

        # 兼容 symbol/code 双字段
        cached = await collection.find_one({
            "$and": [
                {"$or": [{"symbol": code}, {"code": code}]},
                {"updated_at": {"$gte": expire_before}},
            ]
        })
        return cached


_hk_cache_service: Optional[HKCacheService] = None
_hk_cache_service_lock = threading.Lock()


def get_hk_cache_service() -> HKCacheService:
    """获取港股缓存服务实例（线程安全单例）"""
    global _hk_cache_service
    if _hk_cache_service is not None:
        return _hk_cache_service
    with _hk_cache_service_lock:
        # double-check
        if _hk_cache_service is None:
            _hk_cache_service = HKCacheService()
    return _hk_cache_service
