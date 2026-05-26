"""DataInterface — 数据平台统一门面。消费层的唯一入口。"""

import logging
import threading
from typing import Dict, List, Optional

from app.data.core.result import RefreshResult
from app.data.core.reader import Reader
from app.data.core.refresh_service import DataRefreshService
from app.data.core.registry.capability import CapabilityRegistry
from app.data.core.registry.priority import PriorityConfig

logger = logging.getLogger(__name__)

_instance: Optional["DataInterface"] = None
_instance_lock = threading.Lock()


class DataInterface:
    """数据平台统一接口（单例门面）。

    组合 Reader + RefreshService + CapabilityRegistry + PriorityConfig。
    消费层只通过此类访问数据。
    """

    def __init__(self, sync_trigger_callback=None):
        self.reader = Reader()
        self._registry = CapabilityRegistry()
        self._priority = PriorityConfig()
        self.refresh_service = DataRefreshService(self._registry, self._priority)
        self._sync_trigger_callback = sync_trigger_callback

        from app.data.storage.mongo.repositories.metadata_repo import MetadataRepo
        self._metadata_repo = MetadataRepo()

    @classmethod
    def get_instance(cls) -> "DataInterface":
        """获取全局单例。"""
        global _instance
        if _instance is None:
            with _instance_lock:
                if _instance is None:
                    _instance = cls()
        return _instance

    @classmethod
    def reset_instance(cls) -> None:
        """重置单例（测试用）。"""
        global _instance
        with _instance_lock:
            _instance = None

    # ── 数据读取 ──

    async def read(
        self, market: str, domain: str, symbol: Optional[str] = None,
        start_date: Optional[str] = None, end_date: Optional[str] = None,
        filters: Optional[Dict] = None,
    ) -> Dict:
        """读取标准数据。

        Args:
            market: 市场 (CN/HK/US)
            domain: 数据域 (basic_info/daily_quotes/...)
            symbol: 股票代码（可选，不传则查询全量）
            start_date: 起始日期（可选）
            end_date: 结束日期（可选）
            filters: 额外过滤条件（可选，如 list_status/statement_type 等）
        """
        data, freshness = await self.reader.get_data(
            market, domain, symbol,
            start_date=start_date, end_date=end_date,
            filters=filters,
        )
        return {
            "data": data,
            "freshness": freshness,
            "market": market,
            "symbol": symbol,
            "domain": domain,
        }

    # ── 数据刷新 ──

    async def refresh(
        self, market: str, symbol: str,
        domains: Optional[List[str]] = None,
        force: bool = False, timeout: int = 30,
    ) -> RefreshResult:
        """按需刷新指定股票数据。"""
        return await self.refresh_service.refresh(market, symbol, domains, force, timeout)

    # ── 同步管理 ──

    async def trigger_sync(self, market: str, domain: str) -> str:
        """手动触发同步任务。优先走注入的回调，降级走调度引擎，最终降级走记录事件。"""
        from datetime import datetime, timezone

        task_id = f"sync_{market}_{domain}_{int(datetime.now(timezone.utc).timestamp())}"

        # 优先使用注入的回调（由上层 worker 模块注册）
        if self._sync_trigger_callback:
            try:
                result = self._sync_trigger_callback(market, domain)
                if result:
                    logger.info(f"通过回调触发同步: {result}")
                    return result
            except Exception as e:
                logger.warning(f"回调触发失败: {e}")

        # 降级：尝试调度引擎
        try:
            from app.worker.scheduler_setup import get_scheduler_engine
            engine = get_scheduler_engine()
            if engine:
                job_id = await engine.trigger_job(market, domain)
                if job_id:
                    logger.info(f"通过调度引擎触发同步: {job_id}")
                    return job_id
        except Exception as e:
            logger.warning(f"调度引擎触发失败，降级到直接同步: {e}")

        # 降级：只记录事件（实际执行需等调度引擎可用）
        repo = self._metadata_repo
        await repo.insert_event({
            "market": market,
            "event_type": "SYNC_START",
            "domain": domain,
            "task_id": task_id,
        })
        logger.info(f"记录同步事件（降级模式）: {task_id}")
        return task_id

    async def get_sync_status(self, market: str, domain: Optional[str] = None) -> List[Dict]:
        """查询同步检查点列表。"""
        return await self._metadata_repo.get_all_checkpoints(market, domain)

    async def get_sync_events(self, market: str, domain: Optional[str] = None, limit: int = 50) -> List[Dict]:
        """查询同步事件。"""
        return await self._metadata_repo.get_events(market, domain, limit)

    # ── 数据源管理 ──

    async def get_source_health(self, market: str) -> List[Dict]:
        """获取数据源健康状态。优先从 MongoDB 读取，回退到内存监控。"""
        mongo_health = await self._metadata_repo.get_all_health(market)

        if mongo_health:
            return mongo_health

        from app.data.monitoring.source_health import SourceHealthMonitor
        monitor = SourceHealthMonitor()
        return monitor.get_all_health(market)

    def get_capability_registry(self) -> CapabilityRegistry:
        """获取能力注册表。"""
        return self._registry

    # ── 配置管理 ──

    async def get_config(self, market: str, domain: str) -> Optional[Dict]:
        """获取数据源优先级配置。"""
        return await self._metadata_repo.get_config("data_source_priority", market, domain)

    async def update_config(self, market: str, domain: str, sources: List[str], updated_by: str = "user") -> bool:
        """更新数据源优先级。"""
        await self._metadata_repo.upsert_config(
            "data_source_priority", market, domain,
            {"sources": sources}, updated_by,
        )
        self._priority.invalidate_cache(market, domain)
        logger.info(f"更新优先级: {market}/{domain} → {sources}")
        return True

    # ── Dashboard 统计 ──

    async def get_domain_stats(self, market: str, domains: List[str]) -> Dict[str, Dict]:
        """获取各域统计信息（记录数 + 最后更新时间）。"""
        from app.data.storage.mongo.client import get_motor_db
        from app.data.storage.mongo.collections import get_collection_name

        db = get_motor_db()
        stats: Dict[str, Dict] = {}
        for domain in domains:
            try:
                coll = db[get_collection_name(domain, market)]
                count = await coll.count_documents({})
                last_doc = await coll.find_one(
                    {}, {"updated_at": 1}, sort=[("updated_at", -1)],
                )
                stats[domain] = {
                    "records": count,
                    "last_updated": last_doc.get("updated_at") if last_doc else None,
                }
            except Exception as e:
                logger.debug(f"获取域统计失败: {domain}: {e}")
                stats[domain] = {"records": 0, "last_updated": None}
        return stats

    async def get_quotes_stats(self, market: str) -> Dict[str, int]:
        """获取日线行情集合统计（记录数 + 股票数）。"""
        from app.data.storage.mongo.client import get_motor_db
        from app.data.storage.mongo.collections import get_collection_name

        db = get_motor_db()
        coll = db[get_collection_name("daily_quotes", market)]
        total_records = await coll.count_documents({})
        total_symbols = len(await coll.distinct("symbol"))
        return {"total_records": total_records, "total_symbols": total_symbols}

    # ── 数据质量 ──

    async def get_quality_overview(self, market: str, domains: List[str]) -> Dict[str, Dict]:
        """获取各域质量概览（记录数、完整率、最新日期）。"""
        from app.data.storage.mongo.client import get_motor_db
        from app.data.storage.mongo.collections import get_collection_name

        db = get_motor_db()
        overview: Dict[str, Dict] = {}
        for domain in domains:
            try:
                coll = db[get_collection_name(domain, market)]
                total = await coll.count_documents({})
                missing_symbol = await coll.count_documents({"symbol": {"$exists": False}})
                latest_doc = await coll.find_one(
                    {"trade_date": {"$exists": True}},
                    sort=[("trade_date", -1)],
                )
                latest_date = latest_doc.get("trade_date") if latest_doc else None
                overview[domain] = {
                    "total_records": total,
                    "missing_symbol": missing_symbol,
                    "completeness": round((total - missing_symbol) / total, 3) if total > 0 else 1.0,
                    "latest_date": latest_date,
                }
            except Exception as e:
                overview[domain] = {"error": str(e)}
        return overview

    async def check_domain_quality(self, market: str, domain: str) -> Dict:
        """对指定域执行完整质量检查。"""
        from app.data.storage.mongo.client import get_motor_db
        from app.data.storage.mongo.collections import get_collection_name
        from datetime import datetime, timedelta

        _REQUIRED_FIELDS: Dict[str, List[str]] = {
            "daily_quotes": ["symbol", "trade_date", "close"],
            "daily_indicators": ["symbol", "trade_date"],
            "financial": ["symbol", "report_period"],
            "basic_info": ["symbol"],
        }
        _TIMESERIES_DOMAINS = ("daily_quotes", "daily_indicators", "adj_factors")

        db = get_motor_db()
        coll = db[get_collection_name(domain, market)]
        total = await coll.count_documents({})
        stats: Dict = {"total_records": total, "issues": []}

        if total == 0:
            stats["status"] = "empty"
            return stats

        required = _REQUIRED_FIELDS.get(domain, ["symbol"])
        for field in required:
            missing_count = await coll.count_documents({
                "$or": [{field: {"$exists": False}}, {field: None}, {field: ""}],
            })
            if missing_count > 0:
                stats["issues"].append({
                    "type": "missing_field",
                    "field": field,
                    "count": missing_count,
                    "percentage": round(missing_count / total * 100, 2),
                })

        if domain in _TIMESERIES_DOMAINS:
            thirty_days_ago = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
            try:
                pipeline = [
                    {"$match": {"trade_date": {"$gte": thirty_days_ago}}},
                    {"$group": {"_id": "$trade_date", "count": {"$sum": 1}}},
                    {"$sort": {"_id": 1}},
                ]
                cursor = coll.aggregate(pipeline)
                date_counts = await cursor.to_list(length=None)
                trading_days_covered = len(date_counts)
                try:
                    cal_coll = db[get_collection_name("trade_calendar", market)]
                    expected_days = await cal_coll.count_documents({
                        "is_open": 1,
                        "cal_date": {"$gte": thirty_days_ago},
                    })
                except Exception as e:
                    logger.debug(f"交易日历查询失败: {e}")
                    expected_days = None
                stats["date_continuity"] = {
                    "trading_days_covered": trading_days_covered,
                    "expected_trading_days": expected_days,
                    "coverage_rate": round(trading_days_covered / expected_days, 3) if expected_days else None,
                    "period": "last_30_days",
                }
            except Exception as e:
                stats["date_continuity"] = {"error": str(e)}

        if domain == "daily_quotes":
            try:
                bi_coll = db[get_collection_name("basic_info", market)]
                active_stocks = await bi_coll.count_documents({"list_status": "L"})
                if active_stocks > 0:
                    latest = await coll.find_one(sort=[("trade_date", -1)])
                    if latest:
                        latest_date = latest.get("trade_date", "")
                        covered = await coll.count_documents({"trade_date": latest_date})
                        stats["stock_coverage"] = {
                            "active_stocks": active_stocks,
                            "covered_stocks": covered,
                            "coverage_rate": round(covered / active_stocks, 3),
                            "latest_date": latest_date,
                        }
            except Exception as e:
                stats["stock_coverage"] = {"error": str(e)}

        stats["status"] = "ok" if not stats["issues"] else "warning"
        return stats
