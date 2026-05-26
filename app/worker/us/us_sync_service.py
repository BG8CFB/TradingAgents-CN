"""
美股全量同步服务

基于 DataInterface 统一门面实现数据同步，天然幂等。
默认关闭，用户通过 .env 中 US_UNIFIED_ENABLED=true 启用。
"""
import asyncio
import logging
from typing import Any, Dict, List, Optional

from app.core.config import settings
from app.data.storage.mongo.collections import get_collection_name
from app.worker.base_sync_service import BaseSyncService

logger = logging.getLogger(__name__)


class USSyncService(BaseSyncService):
    """美股全量同步服务"""

    market = "US"
    market_name = "美股"

    def __init__(self):
        super().__init__(
            batch_size=settings.US_SYNC_BATCH_SIZE,
            rate_limit_delay=settings.US_SYNC_RATE_LIMIT_DELAY,
        )

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
            coll_name = get_collection_name("basic_info", "US")
            symbols = await db[coll_name].distinct("symbol")
            if symbols:
                logger.info(f"美股列表: 从数据库获取到 {len(symbols)} 只")
                return [s.upper() for s in symbols]
        except Exception as e:
            logger.warning(f"从数据库获取美股列表失败: {e}")

        logger.warning("美股列表: 所有获取方式均失败")
        return []


# ── 全局单例 ──────────────────────────────────────────────────────────

_us_sync_service: Optional[USSyncService] = None
_us_sync_lock = asyncio.Lock()


async def get_us_sync_service() -> USSyncService:
    global _us_sync_service
    if _us_sync_service is not None:
        return _us_sync_service
    async with _us_sync_lock:
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
