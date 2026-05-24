"""
美股全量同步服务

基于 DataInterface 统一门面实现数据同步，天然幂等。
默认关闭，用户通过 .env 中 US_UNIFIED_ENABLED=true 启用。
"""
import asyncio
import logging
import threading
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from app.core.config import settings
from app.data.core.interface import DataInterface
from app.data.storage.mongo.collections import get_collection_name
from app.utils.timezone import now_config_tz, format_date_short, now_utc

logger = logging.getLogger(__name__)


class USSyncService:
    """美股全量同步服务"""

    def __init__(self):
        self.market = "US"
        self._di: Optional[DataInterface] = None
        self.batch_size = settings.US_SYNC_BATCH_SIZE
        self.rate_limit_delay = settings.US_SYNC_RATE_LIMIT_DELAY

    async def initialize(self):
        self._di = DataInterface.get_instance()

    def _get_data_interface(self) -> DataInterface:
        if self._di is None:
            self._di = DataInterface.get_instance()
        return self._di

    async def _get_stock_list(self) -> List[str]:
        """获取美股股票列表（多层策略）"""
        self._get_data_interface()

        # 1. 通过 BasicInfoRepo 获取活跃股票列表
        try:
            from app.data.storage.mongo.repositories.basic_info_repo import BasicInfoRepo
            repo = BasicInfoRepo()
            stocks = await repo.get_active_symbols("US")
            if stocks:
                symbols = [s["symbol"].upper() for s in stocks]
                logger.info(f"美股列表: 从 BasicInfoRepo 获取到 {len(symbols)} 只")
                return symbols
        except Exception as e:
            logger.debug(f"从 BasicInfoRepo 获取美股列表失败: {e}")

        # 2. 尝试通过 Finnhub Provider 获取
        try:
            from app.data.sources.us import get_us_provider
            provider = get_us_provider("finnhub")
            if provider and provider.is_available():
                df = await provider.get_stock_list()
                if df is not None and not df.empty:
                    sym_col = next(
                        (c for c in ["symbol", "Symbol", "代码"] if c in df.columns),
                        None,
                    )
                    if sym_col:
                        symbols = [
                            str(s).strip().upper()
                            for s in df[sym_col].dropna().unique()
                            if str(s).strip() and str(s).strip().isalpha()
                        ]
                        if symbols:
                            logger.info(f"美股列表: 从 Finnhub 获取到 {len(symbols)} 只")
                            return symbols
        except Exception as e:
            logger.debug(f"从 Finnhub 获取美股列表失败: {e}")

        # 3. 兜底：直接从数据库 distinct
        try:
            from app.core.database import get_mongo_db
            db = get_mongo_db()
            coll_name = get_collection_name("US", "basic_info")
            symbols = await db[coll_name].distinct("symbol")
            if symbols:
                logger.info(f"美股列表: 从数据库获取到 {len(symbols)} 只")
                return [s.upper() for s in symbols]
        except Exception as e:
            logger.warning(f"从数据库获取美股列表失败: {e}")

        logger.warning("美股列表: 所有获取方式均失败")
        return []

    async def sync_stock_basic_info(self, force_update: bool = False) -> Dict[str, Any]:
        """同步美股基础信息 — 通过 DataInterface 刷新每只股票"""
        await self._ensure_initialized()
        stats = self._make_stats(task="sync_stock_basic_info")
        di = self._get_data_interface()

        symbols = await self._get_stock_list()
        stats["total_processed"] = len(symbols)
        logger.info(f"开始同步美股基础信息: {len(symbols)} 只股票")

        for idx, symbol in enumerate(symbols, 1):
            if not force_update:
                try:
                    result = await di.read("US", "basic_info", symbol=symbol)
                    data = result.get("data")
                    freshness = result.get("freshness")
                    if data and freshness == "fresh":
                        stats["success_count"] += 1
                        continue
                except Exception:
                    pass

            try:
                refresh_result = await di.refresh(
                    "US", symbol, domains=["basic_info"],
                    force=force_update, timeout=30,
                )
                domain_result = refresh_result.domains.get("basic_info")
                if domain_result and domain_result.status in ("refreshed", "fresh"):
                    stats["success_count"] += 1
                else:
                    stats["error_count"] += 1
            except Exception as e:
                logger.debug(f"美股 {symbol} 同步基础信息失败: {e}")
                stats["error_count"] += 1

            if idx % self.batch_size == 0:
                logger.info(f"美股基础信息同步进度: {idx}/{len(symbols)}")
                await asyncio.sleep(self.rate_limit_delay)

        return self._complete_stats(stats)

    async def sync_daily_quotes(
        self,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        incremental: bool = True,
    ) -> Dict[str, Any]:
        """同步美股日线行情 — 通过 DataInterface 刷新每只股票"""
        await self._ensure_initialized()
        stats = self._make_stats(task="sync_daily_quotes")
        di = self._get_data_interface()

        symbols = await self._get_stock_list()
        stats["total_processed"] = len(symbols)

        if not end_date:
            end_date = format_date_short(now_config_tz())
        if not start_date:
            start_date = format_date_short(now_config_tz() - timedelta(days=30))

        logger.info(f"开始同步美股日线: {len(symbols)} 只, {start_date} ~ {end_date}")

        for idx, symbol in enumerate(symbols, 1):
            actual_start = start_date
            if incremental:
                try:
                    result = await di.read("US", "daily_quotes", symbol=symbol)
                    data = result.get("data")
                    if data and isinstance(data, list) and data:
                        latest_date = data[0].get("trade_date")
                        for record in data:
                            td = record.get("trade_date")
                            if td and (not latest_date or td > latest_date):
                                latest_date = td
                        if latest_date:
                            try:
                                last_dt = datetime.strptime(latest_date, "%Y-%m-%d")
                                actual_start = (last_dt + timedelta(days=1)).strftime("%Y-%m-%d")
                            except ValueError:
                                pass
                except Exception:
                    pass

            if incremental and actual_start > end_date:
                stats["success_count"] += 1
            else:
                try:
                    refresh_result = await di.refresh(
                        "US", symbol, domains=["daily_quotes"],
                        force=True, timeout=30,
                    )
                    domain_result = refresh_result.domains.get("daily_quotes")
                    if domain_result and domain_result.status in ("refreshed", "fresh"):
                        stats["success_count"] += 1
                    else:
                        stats["error_count"] += 1
                except Exception as e:
                    logger.debug(f"美股 {symbol} 同步行情失败: {e}")
                    stats["error_count"] += 1

            if idx % self.batch_size == 0:
                logger.info(f"美股日线同步进度: {idx}/{len(symbols)}")
                await asyncio.sleep(self.rate_limit_delay)

        return self._complete_stats(stats)

    async def run_status_check(self) -> Dict[str, Any]:
        """美股数据源状态检查"""
        await self._ensure_initialized()
        di = self._get_data_interface()

        basic_coll = get_collection_name("US", "basic_info")
        daily_coll = get_collection_name("US", "daily_quotes")

        basic_count = 0
        daily_count = 0
        latest_basic = None
        latest_daily = None

        try:
            from app.core.database import get_mongo_db
            db = get_mongo_db()
            basic_count = await db[basic_coll].count_documents({})
            daily_count = await db[daily_coll].count_documents({})

            doc = await db[basic_coll].find_one({}, sort=[("updated_at", -1)])
            if doc:
                latest_basic = doc.get("updated_at")
            doc = await db[daily_coll].find_one({}, sort=[("trade_date", -1)])
            if doc:
                latest_daily = doc.get("trade_date")
        except Exception as e:
            logger.warning(f"美股状态检查查询数据库失败: {e}")

        available_sources = []
        try:
            health_list = await di.get_source_health("US")
            available_sources = [h.get("source", "") for h in health_list if h.get("healthy")]
        except Exception as e:
            logger.warning(f"获取美股数据源健康状态失败: {e}")

        return {
            "market": "US",
            "basic_info_count": basic_count,
            "daily_quotes_count": daily_count,
            "latest_basic_info_update": str(latest_basic) if latest_basic else None,
            "latest_trade_date": latest_daily,
            "available_sources": available_sources,
        }

    async def _ensure_initialized(self):
        if self._di is None:
            await self.initialize()

    def _make_stats(self, **extra_fields) -> Dict[str, Any]:
        stats = {
            "total_processed": 0,
            "success_count": 0,
            "error_count": 0,
            "start_time": now_utc(),
            "end_time": None,
            "duration": 0,
            "errors": [],
        }
        stats.update(extra_fields)
        return stats

    def _complete_stats(self, stats: Dict[str, Any]) -> Dict[str, Any]:
        stats["end_time"] = now_utc()
        start_time = stats.get("start_time")
        if start_time:
            stats["duration"] = (stats["end_time"] - start_time).total_seconds()
        return stats


# ── 全局单例 ──────────────────────────────────────────────────────────

_us_sync_service: Optional[USSyncService] = None
_us_sync_lock = threading.Lock()


async def get_us_sync_service() -> USSyncService:
    global _us_sync_service
    if _us_sync_service is not None:
        return _us_sync_service
    async with asyncio.Lock():
        if _us_sync_service is None:
            _us_sync_service = USSyncService()
            await _us_sync_service.initialize()
    return _us_sync_service


# ── APScheduler 入口函数 ─────────────────────────────────────────────

async def run_us_basic_info_sync(force_update: bool = False):
    service = await get_us_sync_service()
    result = await service.sync_stock_basic_info(force_update=force_update)
    logger.info(f"美股基础信息同步完成: {result}")
    return result


async def run_us_daily_quotes_sync(incremental: bool = True):
    service = await get_us_sync_service()
    result = await service.sync_daily_quotes(incremental=incremental)
    logger.info(f"美股日线同步完成: {result}")
    return result


async def run_us_status_check():
    service = await get_us_sync_service()
    result = await service.run_status_check()
    logger.info(f"美股状态检查: {result}")
    return result
