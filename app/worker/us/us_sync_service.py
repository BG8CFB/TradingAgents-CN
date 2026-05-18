"""
美股全量同步服务

复用 Orchestrator 写入（warm_stock_info / warm_daily_quotes），天然幂等。
默认关闭，用户通过 .env 中 US_UNIFIED_ENABLED=true 启用。
"""
import asyncio
import logging
import threading
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from app.core.config import settings
from app.data.schema.collections import get_collection_name
from app.utils.timezone import now_utc, now_config_tz, format_date_short
from app.worker.base_sync_service import BaseSyncService

logger = logging.getLogger(__name__)


class USSyncService(BaseSyncService):
    """美股全量同步服务"""

    def __init__(self):
        super().__init__(
            data_source="us_sync",
            batch_size=settings.US_SYNC_BATCH_SIZE,
            rate_limit_delay=settings.US_SYNC_RATE_LIMIT_DELAY,
        )
        self.market = "US"
        self._orchestrators: Optional[List[tuple]] = None

    async def initialize(self):
        from app.core.database import get_mongo_db
        self.db = get_mongo_db()

    def _get_orchestrators(self) -> List[tuple]:
        if self._orchestrators is not None:
            return self._orchestrators

        result = []
        candidates = [
            ("app.data.sources.us.yfinance_us.orchestrator", "YFinanceUSOrchestrator", "yfinance_us"),
            ("app.data.sources.us.finnhub_us.orchestrator", "FinnhubUSOrchestrator", "finnhub_us"),
        ]
        for module_path, class_name, adapter_name in candidates:
            try:
                if "yfinance" in adapter_name:
                    from app.data.sources.us.yfinance_us import get_yfinance_us_adapter
                    adapter = get_yfinance_us_adapter()
                else:
                    from app.data.sources.us.finnhub_us import get_finnhub_us_adapter
                    adapter = get_finnhub_us_adapter()

                if adapter and adapter.provider.is_available():
                    import importlib
                    module = importlib.import_module(module_path)
                    cls = getattr(module, class_name)
                    result.append((cls(adapter), adapter_name))
            except Exception as e:
                logger.debug(f"美股 orchestrator {adapter_name} 不可用: {e}")

        self._orchestrators = result
        logger.info(f"美股可用 orchestrator: {[name for _, name in result]}")
        return result

    async def _get_stock_list(self) -> List[str]:
        """获取美股股票列表（多层策略）"""
        # 1. 如果 Finnhub 可用，使用 Finnhub API
        try:
            from app.data.sources.us.finnhub_us import get_finnhub_us_adapter
            adapter = get_finnhub_us_adapter()
            if adapter and adapter.provider.is_available():
                df = await adapter.provider.get_stock_list()
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

        # 2. 内置股票列表
        try:
            from app.data.us_stock_universe import US_STOCK_UNIVERSE
            logger.info(f"美股列表: 使用内置列表 {len(US_STOCK_UNIVERSE)} 只")
            return list(US_STOCK_UNIVERSE)
        except ImportError:
            pass

        # 3. 备用：从数据库已有缓存读取
        if self.db:
            try:
                coll_name = get_collection_name("US", "basic_info")
                symbols = await self.db[coll_name].distinct("symbol")
                if symbols:
                    logger.info(f"美股列表: 从数据库获取到 {len(symbols)} 只")
                    return [s.upper() for s in symbols]
            except Exception as e:
                logger.warning(f"从数据库获取美股列表失败: {e}")

        logger.warning("美股列表: 所有获取方式均失败")
        return []

    async def sync_stock_basic_info(self, force_update: bool = False) -> Dict[str, Any]:
        """同步美股基础信息"""
        await self._ensure_initialized()
        stats = self.make_stats(task="sync_stock_basic_info")
        orches = self._get_orchestrators()
        if not orches:
            stats["errors"].append("无可用 orchestrator")
            return self.complete_stats(stats)

        symbols = await self._get_stock_list()
        stats["total_processed"] = len(symbols)
        logger.info(f"开始同步美股基础信息: {len(symbols)} 只股票")

        basic_info_coll = get_collection_name("US", "basic_info")

        for idx, symbol in enumerate(symbols, 1):
            if not force_update and self.db:
                existing = await self.db[basic_info_coll].find_one(
                    {"symbol": symbol},
                    {"updated_at": 1},
                )
                if existing and self.is_data_fresh(existing.get("updated_at"), hours=168):
                    stats["success_count"] += 1
                    continue

            synced = False
            for orch, source_name in orches:
                try:
                    ok = await orch.warm_stock_info(symbol)
                    if ok:
                        stats["success_count"] += 1
                        synced = True
                        break
                except Exception as e:
                    logger.debug(f"美股 {symbol} 通过 {source_name} 同步基础信息失败: {e}")

            if not synced:
                stats["error_count"] += 1

            if idx % self.batch_size == 0:
                logger.info(f"美股基础信息同步进度: {idx}/{len(symbols)}")
                await asyncio.sleep(self.rate_limit_delay)

        return self.complete_stats(stats)

    async def sync_daily_quotes(
        self,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        incremental: bool = True,
    ) -> Dict[str, Any]:
        """同步美股日线行情"""
        await self._ensure_initialized()
        stats = self.make_stats(task="sync_daily_quotes")
        orches = self._get_orchestrators()
        if not orches:
            stats["errors"].append("无可用 orchestrator")
            return self.complete_stats(stats)

        symbols = await self._get_stock_list()
        stats["total_processed"] = len(symbols)

        if not end_date:
            end_date = format_date_short(now_config_tz())
        if not start_date:
            start_date = format_date_short(now_config_tz() - timedelta(days=30))

        logger.info(f"开始同步美股日线: {len(symbols)} 只, {start_date} ~ {end_date}")

        daily_coll = get_collection_name("US", "daily_quotes")

        for idx, symbol in enumerate(symbols, 1):
            actual_start = start_date
            if incremental and self.db:
                latest = await self.db[daily_coll].find_one(
                    {"symbol": symbol},
                    {"trade_date": 1},
                    sort=[("trade_date", -1)],
                )
                if latest and latest.get("trade_date"):
                    try:
                        last_dt = datetime.strptime(latest["trade_date"], "%Y-%m-%d")
                        actual_start = (last_dt + timedelta(days=1)).strftime("%Y-%m-%d")
                    except ValueError:
                        pass

            synced = False
            for orch, source_name in orches:
                try:
                    count = await orch.warm_daily_quotes(symbol, actual_start, end_date)
                    if count and count > 0:
                        stats["success_count"] += 1
                        synced = True
                        break
                    synced = True
                    break
                except Exception as e:
                    logger.debug(f"美股 {symbol} 通过 {source_name} 同步行情失败: {e}")

            if not synced:
                stats["error_count"] += 1

            if idx % self.batch_size == 0:
                logger.info(f"美股日线同步进度: {idx}/{len(symbols)}")
                await asyncio.sleep(self.rate_limit_delay)

        return self.complete_stats(stats)

    async def run_status_check(self) -> Dict[str, Any]:
        """美股数据源状态检查"""
        await self._ensure_initialized()
        basic_coll = get_collection_name("US", "basic_info")
        daily_coll = get_collection_name("US", "daily_quotes")

        basic_count = await self.db[basic_coll].count_documents({}) if self.db else 0
        daily_count = await self.db[daily_coll].count_documents({}) if self.db else 0

        latest_basic = None
        latest_daily = None
        if self.db:
            doc = await self.db[basic_coll].find_one({}, sort=[("updated_at", -1)])
            if doc:
                latest_basic = doc.get("updated_at")
            doc = await self.db[daily_coll].find_one({}, sort=[("trade_date", -1)])
            if doc:
                latest_daily = doc.get("trade_date")

        orches = self._get_orchestrators()
        available_sources = [name for _, name in orches]

        return {
            "market": "US",
            "basic_info_count": basic_count,
            "daily_quotes_count": daily_count,
            "latest_basic_info_update": str(latest_basic) if latest_basic else None,
            "latest_trade_date": latest_daily,
            "available_sources": available_sources,
        }

    async def _ensure_initialized(self):
        if self.db is None:
            await self.initialize()


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
