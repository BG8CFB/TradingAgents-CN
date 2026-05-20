"""
数据同步服务基类
抽取 Tushare/AKShare/BaoStock 三个同步服务的公共逻辑
"""
import asyncio
import logging
from abc import ABC
from datetime import datetime, timedelta
from typing import Any, Dict

from app.utils.timezone import now_utc, now_config_tz, format_date_short

logger = logging.getLogger(__name__)


class BaseSyncService(ABC):
    """
    数据同步服务基类

    提供三个同步服务的公共方法：
    - get_last_sync_date(): 增量日期获取
    - is_data_fresh(): 数据新鲜度检查
    - make_stats(): 标准统计字典创建
    - complete_stats(): 统计字典完成（填充 end_time/duration）
    """

    def __init__(self, data_source: str, batch_size: int = 100, rate_limit_delay: float = 0.1):
        """
        初始化同步服务基类

        Args:
            data_source: 数据源标识（"tushare" / "akshare" / "baostock"）
            batch_size: 批量处理大小
            rate_limit_delay: API调用间隔（秒）
        """
        self.data_source = data_source
        self.batch_size = batch_size
        self.rate_limit_delay = rate_limit_delay
        self.db = None
        self.historical_service = None

    async def get_last_sync_date(self, symbol: str = None) -> str:
        """
        获取最后同步日期（增量策略）

        策略：
        1. 如果传了 symbol：获取该股票的最新同步日期，返回下一天（避免重复同步）
        2. 如果无历史数据，查找上市日期(list_date)，从上市日期开始全量同步
        3. 如果也没有上市日期，从 1990-01-01 开始
        4. 如果没传 symbol：返回 30 天前（确保不漏数据）
        5. 异常时：返回 30 天前

        Args:
            symbol: 股票代码，如果提供则返回该股票的最后日期+1天

        Returns:
            日期字符串 (YYYY-MM-DD)
        """
        try:
            # 延迟初始化历史数据服务
            if self.historical_service is None:
                from app.services.historical_data_service import get_historical_data_service
                self.historical_service = await get_historical_data_service()

            if symbol:
                # 获取特定股票的最新日期
                latest_date = await self.historical_service.get_latest_date(symbol, self.data_source)
                if latest_date:
                    # 返回最后日期的下一天（避免重复同步）
                    try:
                        last_date_obj = datetime.strptime(latest_date, '%Y-%m-%d')
                        next_date = last_date_obj + timedelta(days=1)
                        return next_date.strftime('%Y-%m-%d')
                    except ValueError:
                        # 如果日期格式不对，直接返回
                        return latest_date
                else:
                    # 没有历史数据时，从上市日期开始全量同步
                    return await self._get_list_date_or_default(symbol)

            # 默认返回30天前（确保不漏数据）
            return format_date_short(now_config_tz() - timedelta(days=30))

        except Exception as e:
            logger.error(f"获取最后同步日期失败 {symbol}: {e}")
            # 出错时返回30天前，确保不漏数据
            return format_date_short(now_config_tz() - timedelta(days=30))

    async def _get_list_date_or_default(self, symbol: str) -> str:
        """
        获取股票上市日期，如果获取失败则返回默认值

        Args:
            symbol: 股票代码

        Returns:
            上市日期字符串或默认值 "1990-01-01"
        """
        if self.db is None:
            logger.warning(f"{symbol}: 数据库未初始化，从1990-01-01开始同步")
            return "1990-01-01"

        try:
            stock_info = await self.db.stock_basic_info.find_one(
                {"code": symbol},
                {"list_date": 1}
            )
            if stock_info and stock_info.get("list_date"):
                list_date = stock_info["list_date"]
                # 处理不同的日期格式
                if isinstance(list_date, str):
                    # 格式可能是 "20100101" 或 "2010-01-01"
                    if len(list_date) == 8 and list_date.isdigit():
                        return f"{list_date[:4]}-{list_date[4:6]}-{list_date[6:]}"
                    else:
                        return list_date
                else:
                    return list_date.strftime('%Y-%m-%d')

            # 如果没有上市日期，从1990年开始
            logger.warning(f"{symbol}: 未找到上市日期，从1990-01-01开始同步")
            return "1990-01-01"

        except Exception as e:
            logger.warning(f"{symbol}: 获取上市日期失败: {e}，从1990-01-01开始同步")
            return "1990-01-01"

    def is_data_fresh(self, updated_at: Any, hours: int = 24) -> bool:
        """
        检查数据是否新鲜

        Args:
            updated_at: 更新时间。期望传入 UTC 时间（datetime 对象或 ISO 格式字符串）。
                        如果是 aware datetime 或带 'Z' 后缀的 ISO 字符串，会自动去掉时区信息
                        后与 now_utc() 进行 naive 比较。如果上游存入的是本地时间（如 CST），
                        则比较结果可能存在时区偏差。
            hours: 新鲜度阈值（小时）

        Returns:
            是否新鲜
        """
        if not updated_at:
            return False

        try:
            if isinstance(updated_at, str):
                updated_at = datetime.fromisoformat(updated_at.replace('Z', '+00:00'))
            elif isinstance(updated_at, datetime):
                pass
            else:
                return False

            # 去掉时区信息，统一比较
            if updated_at.tzinfo is not None:
                updated_at = updated_at.replace(tzinfo=None)

            now = now_utc()
            # now_utc() 返回的可能是 aware datetime，统一去掉 tzinfo
            if now.tzinfo is not None:
                now = now.replace(tzinfo=None)

            time_diff = now - updated_at
            return time_diff.total_seconds() < (hours * 3600)

        except Exception as e:
            logger.debug(f"检查数据新鲜度失败: {e}")
            return False

    def make_stats(self, **extra_fields) -> Dict[str, Any]:
        """
        创建标准统计字典

        Args:
            **extra_fields: 额外的统计字段

        Returns:
            标准统计字典
        """
        stats = {
            "total_processed": 0,
            "success_count": 0,
            "error_count": 0,
            "start_time": now_utc(),
            "end_time": None,
            "duration": 0,
            "errors": []
        }
        stats.update(extra_fields)
        return stats

    def complete_stats(self, stats: Dict[str, Any]) -> Dict[str, Any]:
        """
        完成统计（填充 end_time 和 duration）

        Args:
            stats: 统计字典

        Returns:
            更新后的统计字典
        """
        stats["end_time"] = now_utc()
        start_time = stats.get("start_time")
        if start_time:
            stats["duration"] = (stats["end_time"] - start_time).total_seconds()
        return stats


# ============================================================================
# 境外市场按需缓存服务基类（HK / US 共用）
# ============================================================================

import threading
from typing import Any, Dict, List, Optional, Set

from app.core.database import get_mongo_db
from app.data.config import get_enabled_sources
from app.data.schema.collections import get_collection_name

_DEFAULT_CACHE_HOURS = 24
_DEFAULT_QUOTES_DAYS = 30


class ForeignMarketCacheService:
    """
    境外市场按需缓存服务基类（HK / US 共用）

    子类仅需设置:
        - market: "HK" | "US"
        - orchestrator_map: 数据源名称 -> (orch_module, orch_class, adapter_module, adapter_factory)
        - normalize_code(code): 代码标准化方法
        - _log_label: 日志前缀
    """

    market: str = ""
    orchestrator_map: Dict[str, tuple] = {}
    _log_label: str = ""

    def __init__(self):
        self._basic_info_collection = get_collection_name(self.market, "basic_info")
        self._daily_quotes_collection = get_collection_name(self.market, "daily_quotes")
        self._batch_task: Optional[Dict[str, Any]] = None
        self._batch_lock = threading.Lock()

    def normalize_code(self, code: str) -> str:
        raise NotImplementedError

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
        sources = get_enabled_sources(self.market)
        result = []
        for src in sources:
            if src in self.orchestrator_map:
                result.append(self.orchestrator_map[src])
        return result

    def _get_orchestrator_instance(self, orch_info):
        orch_module, orch_class, adapter_module, adapter_factory = orch_info
        import importlib
        mod = importlib.import_module(adapter_module)
        adapter = getattr(mod, adapter_factory)()
        orch_mod = importlib.import_module(orch_module)
        return getattr(orch_mod, orch_class)(adapter)

    async def get_stock_info(self, stock_code: str) -> Optional[Dict[str, Any]]:
        normalized_code = self.normalize_code(stock_code)
        cached = await self._get_cached_info(normalized_code)
        if cached:
            return cached
        for orch_info in self._get_orchestrators():
            try:
                orch = self._get_orchestrator_instance(orch_info)
                success = await orch.warm_stock_info(normalized_code)
                if success:
                    cached = await self._get_cached_info(normalized_code)
                    if cached:
                        return cached
            except Exception as e:
                logger.warning(f"⚠️ [{self._log_label}] {stock_code} 预热失败: {e}")
                continue
        logger.warning(f"⚠️ [{self._log_label}] {stock_code} 所有数据源均失败")
        return None

    async def refresh_cache(self, stock_code: str) -> Optional[Dict[str, Any]]:
        normalized_code = self.normalize_code(stock_code)
        for orch_info in self._get_orchestrators():
            try:
                orch = self._get_orchestrator_instance(orch_info)
                await orch.warm_stock_info(normalized_code)
            except Exception as e:
                logger.warning(f"⚠️ [{self._log_label}] 刷新 {stock_code} 失败: {e}")
        return await self._get_cached_info(normalized_code)

    async def warm_stock_with_quotes(self, stock_code: str, force: bool = False) -> Dict[str, Any]:
        normalized_code = self.normalize_code(stock_code)
        now = now_config_tz()
        start_date = (now - timedelta(days=_DEFAULT_QUOTES_DAYS)).strftime("%Y-%m-%d")
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
                        logger.warning(f"⚠️ [{self._log_label}] {stock_code} 行情预热失败（基础信息已缓存）: {e}")
                        quotes_count = 0
                    used_source = orch_info[0].split('.')[-2].replace(f'_{self.market.lower()}', '').upper()
                    break
            except Exception as e:
                logger.warning(f"⚠️ [{self._log_label}] 预热 {stock_code} 失败: {e}")
                continue

        return {
            "symbol": normalized_code,
            "info_success": info_ok,
            "quotes_count": quotes_count,
            "source": used_source,
        }

    async def warm_batch(self, symbols: List[str], force: bool = False) -> str:
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
        with self._batch_lock:
            if self._batch_task is None:
                return {"status": "idle", "total": 0, "completed": 0, "failed": 0, "results": []}
            return dict(self._batch_task)

    async def list_cached_stocks(self, page: int = 1, page_size: int = 20) -> Dict[str, Any]:
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
        expire_before = now_config_tz() - timedelta(hours=_DEFAULT_CACHE_HOURS)

        total_documents = await collection.count_documents({})
        valid_documents = await collection.count_documents({"updated_at": {"$gte": expire_before}})
        latest_doc = await collection.find_one({}, sort=[("updated_at", -1)])

        return {
            "market": self.market,
            "cache_hours": _DEFAULT_CACHE_HOURS,
            "available_sources": get_enabled_sources(self.market),
            "collection": self._basic_info_collection,
            "cached_symbols": await self._count_cached_symbols(),
            "total_documents": total_documents,
            "valid_documents": valid_documents,
            "expired_documents": max(total_documents - valid_documents, 0),
            "last_updated": latest_doc.get("updated_at") if latest_doc else None,
            "latest_symbol": (latest_doc or {}).get("symbol") or (latest_doc or {}).get("code"),
        }

    async def clear_expired_cache(self) -> Dict[str, Any]:
        expire_before = now_config_tz() - timedelta(hours=_DEFAULT_CACHE_HOURS)
        result = await self._get_db()[self._basic_info_collection].delete_many(
            {"updated_at": {"$lt": expire_before}}
        )
        return {
            "market": self.market,
            "collection": self._basic_info_collection,
            "deleted_count": result.deleted_count,
            "expire_before": expire_before,
        }

    async def _get_cached_info(self, code: str) -> Optional[Dict[str, Any]]:
        collection = self._get_db()[self._basic_info_collection]
        expire_before = now_config_tz() - timedelta(hours=_DEFAULT_CACHE_HOURS)

        cached = await collection.find_one({
            "$and": [
                {"$or": [{"symbol": code}, {"code": code}]},
                {"updated_at": {"$gte": expire_before}},
            ]
        })
        return cached
