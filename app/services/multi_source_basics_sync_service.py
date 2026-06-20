"""
Multi-source stock basics synchronization service
- Supports multiple data sources with fallback mechanism
- Priority: Tushare > AKShare > BaoStock 
- Fetches A-share stock basic info with extended financial metrics
- Upserts into MongoDB collection `stock_basic_info`
- Provides unified interface for different data sources
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from app.utils.timezone import now_utc, format_iso
from typing import Any, Dict, List, Optional, Tuple
from enum import Enum

from motor.motor_asyncio import AsyncIOMotorDatabase
from pymongo import UpdateOne

from app.core.database import get_mongo_db
from app.data.storage.mongo.collections import get_collection_name
from app.services.basics_sync import add_financial_metrics as _add_financial_metrics_util


logger = logging.getLogger(__name__)

# Collection names
COLLECTION_NAME = get_collection_name("basic_info", "CN")
STATUS_COLLECTION = "sync_status"
JOB_KEY = "stock_basics_multi_source"


class DataSourcePriority(Enum):
    """数据源优先级枚举"""
    TUSHARE = 1
    AKSHARE = 2
    BAOSTOCK = 3


@dataclass
class SyncStats:
    """同步统计信息"""
    job: str = JOB_KEY
    data_type: str = "stock_basics"  # 添加data_type字段以符合数据库索引要求
    status: str = "idle"
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    total: int = 0
    inserted: int = 0
    updated: int = 0
    errors: int = 0
    last_trade_date: Optional[str] = None
    data_sources_used: List[str] = field(default_factory=list)
    source_stats: Dict[str, Dict[str, int]] = field(default_factory=dict)
    message: Optional[str] = None


class MultiSourceBasicsSyncService:
    """多数据源股票基础信息同步服务"""

    def __init__(self):
        self._lock = asyncio.Lock()
        self._running = False
        self._last_status: Optional[Dict[str, Any]] = None
        self._stale_cleaned = False

    async def get_status(self) -> Dict[str, Any]:
        """获取同步状态"""
        # 首次调用时清理陈旧的 running 状态（容器重启后残留）
        if not self._stale_cleaned:
            self._stale_cleaned = True
            await self._cleanup_stale_running_status()

        if self._last_status:
            return self._last_status

        db = get_mongo_db()
        doc = await db[STATUS_COLLECTION].find_one({"job": JOB_KEY})
        if doc:
            doc.pop("_id", None)
            return doc
        return {"job": JOB_KEY, "status": "never_run"}

    async def _cleanup_stale_running_status(self) -> None:
        """清理容器重启后残留的陈旧 running 状态"""
        try:
            if self._running:
                return
            db = get_mongo_db()
            stale = await db[STATUS_COLLECTION].find_one(
                {"job": JOB_KEY, "status": "running"}
            )
            if stale:
                logger.warning("检测到陈旧的 running 状态，自动标记为 failed（容器可能重启过）")
                await db[STATUS_COLLECTION].update_one(
                    {"job": JOB_KEY, "status": "running"},
                    {"$set": {
                        "status": "failed",
                        "message": "同步被中断（服务重启），请重新运行同步",
                        "finished_at": format_iso(now_utc()),
                    }},
                )
                self._last_status = None
        except Exception as e:
            logger.warning(f"清理陈旧状态失败: {e}")

    async def _persist_status(self, db: AsyncIOMotorDatabase, stats: Dict[str, Any]) -> None:
        """持久化同步状态"""
        stats["job"] = JOB_KEY

        # 使用 upsert 来避免重复键错误
        # 基于 data_type 和 job 进行更新或插入
        filter_query = {
            "data_type": stats.get("data_type", "stock_basics"),
            "job": JOB_KEY
        }

        await db[STATUS_COLLECTION].update_one(
            filter_query,
            {"$set": stats},
            upsert=True
        )

        self._last_status = {k: v for k, v in stats.items() if k != "_id"}

    async def _execute_bulk_write_with_retry(
        self,
        db: AsyncIOMotorDatabase,
        operations: List,
        max_retries: int = 3
    ) -> Tuple[int, int]:
        """
        执行批量写入，带重试机制

        Args:
            db: MongoDB数据库实例
            operations: 批量操作列表
            max_retries: 最大重试次数

        Returns:
            (新增数量, 更新数量)
        """
        inserted = 0
        updated = 0
        retry_count = 0

        while retry_count < max_retries:
            try:
                result = await db[COLLECTION_NAME].bulk_write(operations, ordered=False)
                inserted = result.upserted_count
                updated = result.modified_count
                logger.debug(f"✅ 批量写入成功: 新增 {inserted}, 更新 {updated}")
                return inserted, updated

            except asyncio.TimeoutError as e:
                retry_count += 1
                if retry_count < max_retries:
                    wait_time = 2 ** retry_count  # 指数退避：2秒、4秒、8秒
                    logger.warning(f"⚠️ 批量写入超时 (第{retry_count}次重试)，等待{wait_time}秒后重试...")
                    await asyncio.sleep(wait_time)
                else:
                    logger.error(f"❌ 批量写入失败，已重试{max_retries}次: {e}")
                    return 0, 0

            except Exception as e:
                logger.error(f"❌ 批量写入失败: {e}")
                return 0, 0

        return inserted, updated

    async def run_full_sync(self, force: bool = False, preferred_sources: List[str] = None) -> Dict[str, Any]:
        """
        运行完整同步

        Args:
            force: 是否强制运行（即使已在运行中）
            preferred_sources: 优先使用的数据源列表
        """
        async with self._lock:
            if self._running and not force:
                logger.info("Multi-source stock basics sync already running; skip start")
                return await self.get_status()
            self._running = True

        db = get_mongo_db()
        stats = SyncStats()
        stats.started_at = format_iso(now_utc())
        stats.status = "running"
        await self._persist_status(db, stats.__dict__.copy())

        try:
            # Step 1: 通过新架构获取数据源和股票列表
            from app.data.processor.fallback_router import FallbackRouter
            import pandas as pd

            # 使用进程级单例（与 sync_job / refresh_service 共享熔断器 + 限流器）
            router = FallbackRouter.get_instance()
            from app.data.core.registry.priority import PriorityConfig
            priority = PriorityConfig()

            # 获取可用数据源列表
            cn_sources = priority.get_default_sources("CN", "basic_info")
            if not cn_sources:
                raise RuntimeError("No available data sources found")

            logger.info(f"Available data sources: {cn_sources}")
            if preferred_sources:
                logger.info(f"Using preferred data sources: {preferred_sources}")

            # Step 2: 获取股票列表
            try:
                fetch_result = await asyncio.wait_for(
                    router.fetch("CN", "basic_info", "__all__"),
                    timeout=120,
                )
                if fetch_result.success and fetch_result.data:
                    stock_df = pd.DataFrame(fetch_result.data)
                    source_used = fetch_result.source or cn_sources[0]
                else:
                    # 回退到 MongoDB 已有数据
                    from app.data.storage.mongo.client import get_motor_db
                    from app.data.storage.mongo.collections import get_collection_name
                    mdb = get_motor_db()
                    existing = await mdb[get_collection_name("basic_info", "CN")].find(
                        {}, {"_id": 0}
                    ).to_list(length=None)
                    if existing:
                        stock_df = pd.DataFrame(existing)
                        source_used = "mongodb_cache"
                    else:
                        raise RuntimeError("无法获取股票列表")
            except asyncio.TimeoutError:
                raise RuntimeError("获取股票列表超时（120秒），请检查数据源网络连通性")
            if stock_df is None or getattr(stock_df, "empty", True):
                raise RuntimeError("All data sources failed to provide stock list")

            stats.data_sources_used.append(f"stock_list:{source_used}")
            logger.info(f"Successfully fetched {len(stock_df)} stocks from {source_used}")

            # Step 3: 获取最新交易日期和每日指标
            try:
                cal_result = await asyncio.wait_for(
                    router.fetch("CN", "trade_calendar", "__calendar__"),
                    timeout=60,
                )
                if cal_result.success and cal_result.data:
                    cal_df = pd.DataFrame(cal_result.data)
                    open_days = cal_df[cal_df.get("is_open", pd.Series(dtype=bool)).astype(bool)]
                    if not open_days.empty:
                        latest_trade_date = str(open_days["cal_date"].max())
                    else:
                        latest_trade_date = None
                else:
                    latest_trade_date = None
            except asyncio.TimeoutError:
                logger.warning("获取最新交易日期超时（60秒），继续同步但不包含每日基础数据")
                latest_trade_date = None
            stats.last_trade_date = latest_trade_date

            daily_data_map = {}
            daily_source = ""
            if latest_trade_date:
                try:
                    indicator_result = await asyncio.wait_for(
                        router.fetch("CN", "daily_indicators", "__all__",
                                     start_date=latest_trade_date, end_date=latest_trade_date),
                        timeout=120,
                    )
                    if indicator_result.success and indicator_result.data:
                        daily_df = pd.DataFrame(indicator_result.data)
                        daily_source = indicator_result.source or cn_sources[0]
                    else:
                        daily_df = None
                except asyncio.TimeoutError:
                    logger.warning("获取每日基础数据超时（120秒），跳过财务指标")
                    daily_df = None
                if daily_df is not None and not daily_df.empty:
                    for _, row in daily_df.iterrows():
                        sym = row.get("symbol") or row.get("ts_code", "")
                        if sym:
                            daily_data_map[sym] = row.to_dict()
                    stats.data_sources_used.append(f"daily_data:{daily_source}")

            # Step 5: 处理和更新数据（分批处理）
            ops = []
            inserted = updated = errors = 0
            batch_size = 500
            total_stocks = len(stock_df)
            # 设置总量，前端才能计算进度百分比
            stats.total = total_stocks
            await self._persist_status(db, stats.__dict__.copy())

            logger.info(f"🚀 开始处理 {total_stocks} 只股票，数据源: {source_used}")

            for idx, (_, row) in enumerate(stock_df.iterrows(), 1):
                try:
                    # 提取基础信息
                    name = row.get("name") or ""
                    area = row.get("area") or ""
                    industry = row.get("industry") or ""
                    market = row.get("market") or ""
                    list_date = row.get("list_date") or ""
                    ts_code = row.get("ts_code") or ""

                    # 提取6位股票代码
                    if isinstance(ts_code, str) and "." in ts_code:
                        code = ts_code.split(".")[0]
                    else:
                        symbol = row.get("symbol") or ""
                        code = str(symbol).zfill(6) if symbol else ""

                    # 根据 ts_code 判断交易所
                    if isinstance(ts_code, str):
                        if ts_code.endswith(".SH"):
                            sse = "上海证券交易所"
                        elif ts_code.endswith(".SZ"):
                            sse = "深圳证券交易所"
                        elif ts_code.endswith(".BJ"):
                            sse = "北京证券交易所"
                        else:
                            sse = "未知"
                    else:
                        sse = "未知"


                    # 获取财务数据
                    daily_metrics = {}
                    if isinstance(ts_code, str) and ts_code in daily_data_map:
                        daily_metrics = daily_data_map[ts_code]

                    # 生成 full_symbol（确保不为空）
                    full_symbol = ts_code if ts_code else self._generate_full_symbol(code)

                    # 🔥 确定数据源标识
                    # 根据实际使用的数据源设置 source 字段
                    # 注意：不再使用 "multi_source" 作为默认值，必须有明确的数据源
                    if not source_used:
                        logger.warning(f"⚠️ 股票 {code} 没有明确的数据源，跳过")
                        errors += 1
                        continue
                    data_source = source_used

                    # 构建文档
                    doc = {
                        "symbol": code,
                        "name": name,
                        "area": area,
                        "industry": industry,
                        "market": market,
                        "list_date": list_date,
                        "sse": sse,
                        "full_symbol": full_symbol,
                        "data_source": data_source,
                        "updated_at": now_utc(),
                    }

                    # 添加财务指标
                    self._add_financial_metrics(doc, daily_metrics)

                    ops.append(UpdateOne({"symbol": code, "data_source": data_source}, {"$set": doc}, upsert=True))

                except Exception as e:
                    logger.error(f"Error processing stock {row.get('ts_code', 'unknown')}: {e}")
                    errors += 1

                # 🔥 分批执行数据库操作
                if len(ops) >= batch_size or idx == total_stocks:
                    if ops:
                        progress_pct = (idx / total_stocks) * 100
                        logger.info(f"📝 执行批量写入: {len(ops)} 条记录 ({idx}/{total_stocks}, {progress_pct:.1f}%)")

                        batch_inserted, batch_updated = await self._execute_bulk_write_with_retry(db, ops)

                        if batch_inserted > 0 or batch_updated > 0:
                            inserted += batch_inserted
                            updated += batch_updated
                            logger.info(f"✅ 批量写入完成: 新增 {batch_inserted}, 更新 {batch_updated} | 累计: 新增 {inserted}, 更新 {updated}, 错误 {errors}")
                        else:
                            errors += len(ops)
                            logger.warning(f"⚠️ 批量写入失败，标记 {len(ops)} 条记录为错误")

                        ops = []

                        # 每批次完成后持久化进度，让前端能实时看到百分比
                        stats.inserted = inserted
                        stats.updated = updated
                        stats.errors = errors
                        await self._persist_status(db, stats.__dict__.copy())

            # Step 7: 更新统计信息
            stats.inserted = inserted
            stats.updated = updated
            stats.errors = errors
            stats.status = "success" if errors == 0 else "success_with_errors"
            stats.finished_at = format_iso(now_utc())

            await self._persist_status(db, stats.__dict__.copy())
            logger.info(
                f"✅ Multi-source sync finished: total={stats.total} inserted={inserted} "
                f"updated={updated} errors={errors} sources={stats.data_sources_used}"
            )
            return stats.__dict__

        except Exception as e:
            stats.status = "failed"
            stats.message = str(e)
            stats.finished_at = format_iso(now_utc())
            await self._persist_status(db, stats.__dict__.copy())
            logger.exception(f"Multi-source sync failed: {e}")
            return stats.__dict__
        finally:
            async with self._lock:
                self._running = False

    async def reset_state(self) -> None:
        """安全地重置同步服务状态（供外部调用，避免直接访问私有属性）"""
        async with self._lock:
            self._running = False
            logger.info("Multi-source sync state has been reset")



    def _add_financial_metrics(self, doc: Dict, daily_metrics: Dict) -> None:
        """委托到 basics_sync.processing.add_financial_metrics"""
        return _add_financial_metrics_util(doc, daily_metrics)

    def _generate_full_symbol(self, code: str) -> str:
        """根据股票代码生成完整标准化代码 — 委托到全局统一函数"""
        from app.data.schema.base.markets import get_full_symbol
        if not code:
            return ""
        return get_full_symbol(str(code).strip(), "CN")


# 全局服务实例
_multi_source_sync_service = None

def get_multi_source_sync_service() -> MultiSourceBasicsSyncService:
    """获取多数据源同步服务实例"""
    global _multi_source_sync_service
    if _multi_source_sync_service is None:
        _multi_source_sync_service = MultiSourceBasicsSyncService()
    return _multi_source_sync_service
