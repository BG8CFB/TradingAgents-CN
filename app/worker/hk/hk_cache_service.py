"""
港股按需缓存服务

通过 sources/hk/ 编排模块（Provider → Adapter → Schema → MongoDB）获取数据。
"""

import asyncio
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

# 行情预热默认天数
DEFAULT_QUOTES_DAYS = 30


class HKCacheService:
    """港股按需缓存服务"""

    def __init__(self):
        self._basic_info_collection = get_collection_name("HK", "basic_info")
        self._daily_quotes_collection = get_collection_name("HK", "daily_quotes")
        self._batch_task: Optional[Dict[str, Any]] = None
        self._batch_lock = threading.Lock()

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

    async def warm_stock_with_quotes(self, stock_code: str, force: bool = False) -> Dict[str, Any]:
        """预热单只股票的基础信息+最近行情"""
        normalized_code = stock_code.lstrip('0').zfill(5)
        now = now_config_tz()
        start_date = (now - timedelta(days=DEFAULT_QUOTES_DAYS)).strftime("%Y-%m-%d")
        end_date = now.strftime("%Y-%m-%d")

        info_ok = False
        quotes_count = 0
        used_source = None

        for orch_info in self._get_orchestrators():
            try:
                orch = self._get_orchestrator_instance(orch_info)
                info_ok = await orch.warm_stock_info(normalized_code)
                if info_ok:
                    try:
                        quotes_count = await orch.warm_daily_quotes(normalized_code, start_date, end_date)
                    except Exception as e:
                        logger.warning(f"⚠️ [港股缓存] {stock_code} 行情预热失败（基础信息已缓存）: {e}")
                        quotes_count = 0
                    used_source = orch_info[0].split('.')[-2].replace('_hk', '').upper()
                    break
            except Exception as e:
                logger.warning(f"⚠️ [港股缓存] 预热 {stock_code} 失败: {e}")
                continue

        return {
            "symbol": normalized_code,
            "info_success": info_ok,
            "quotes_count": quotes_count,
            "source": used_source,
        }

    async def warm_batch(self, symbols: List[str], force: bool = False) -> str:
        """批量预热，后台执行，返回 task_id"""
        import uuid
        task_id = str(uuid.uuid4())[:8]

        with self._batch_lock:
            self._batch_task = {
                "task_id": task_id,
                "status": "running",
                "total": len(symbols),
                "completed": 0,
                "failed": 0,
                "results": [],
            }

        async def _run():
            for symbol in symbols:
                try:
                    result = await self.warm_stock_with_quotes(symbol, force)
                    with self._batch_lock:
                        if self._batch_task and self._batch_task["task_id"] == task_id:
                            self._batch_task["completed"] += 1
                            self._batch_task["results"].append({
                                "symbol": symbol,
                                "success": result["info_success"],
                                "message": f"基础信息: {'成功' if result['info_success'] else '失败'}, 行情: {result['quotes_count']}条",
                            })
                except Exception as e:
                    with self._batch_lock:
                        if self._batch_task and self._batch_task["task_id"] == task_id:
                            self._batch_task["failed"] += 1
                            self._batch_task["completed"] += 1
                            self._batch_task["results"].append({
                                "symbol": symbol,
                                "success": False,
                                "message": str(e),
                            })

            with self._batch_lock:
                if self._batch_task and self._batch_task["task_id"] == task_id:
                    self._batch_task["status"] = "completed"

        asyncio.ensure_future(_run())
        return task_id

    def get_batch_status(self) -> Optional[Dict[str, Any]]:
        """获取批量预热进度"""
        with self._batch_lock:
            if self._batch_task is None:
                return {"status": "idle", "total": 0, "completed": 0, "failed": 0, "results": []}
            return dict(self._batch_task)

    async def list_cached_stocks(self, page: int = 1, page_size: int = 20) -> Dict[str, Any]:
        """分页获取已缓存股票列表"""
        collection = self._get_db()[self._basic_info_collection]
        skip = (page - 1) * page_size

        total = await collection.count_documents({})
        cursor = collection.find(
            {},
            {"symbol": 1, "name": 1, "data_source": 1, "updated_at": 1, "_id": 0},
        ).sort("updated_at", -1).skip(skip).limit(page_size)
        records = await cursor.to_list(length=page_size)

        return {
            "records": records,
            "total": total,
            "page": page,
            "page_size": page_size,
            "has_more": skip + page_size < total,
        }

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
