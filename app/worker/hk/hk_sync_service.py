"""
港股全量同步服务

基于 DataInterface 统一门面实现数据同步，天然幂等。
默认关闭，用户通过 .env 中 HK_UNIFIED_ENABLED=true 启用。
"""
import asyncio
import logging
from typing import List, Optional

from app.core.config import settings
from app.data.storage.mongo.collections import get_collection_name
from app.worker.base_sync_service import BaseSyncService

logger = logging.getLogger(__name__)


class HKSyncService(BaseSyncService):
    """港股全量同步服务"""

    market = "HK"
    market_name = "港股"

    def __init__(self):
        super().__init__(
            batch_size=settings.HK_SYNC_BATCH_SIZE,
            rate_limit_delay=settings.HK_SYNC_RATE_LIMIT_DELAY,
        )

    async def _get_stock_list(self) -> List[str]:
        """获取港股全市场股票列表"""
        self._get_data_interface()

        # 1. 通过 BasicInfoRepo 获取活跃股票列表
        try:
            from app.data.storage.mongo.repositories.basic_info_repo import BasicInfoRepo
            repo = BasicInfoRepo()
            stocks = await repo.get_active_symbols("HK")
            if stocks:
                symbols = [s["symbol"] for s in stocks]
                logger.info(f"港股列表: 从 BasicInfoRepo 获取到 {len(symbols)} 只")
                return symbols
        except Exception as e:
            logger.warning(f"从 BasicInfoRepo 获取港股列表失败: {e}")

        # 2. 备用：尝试通过 Provider 获取
        try:
            from app.data.sources.hk import get_hk_provider
            for source_name in ("akshare_hk", "tushare_hk", "yfinance_hk"):
                provider = get_hk_provider(source_name)
                if provider and provider.is_available():
                    df = await provider.get_stock_list()
                    if df is not None and not df.empty:
                        code_col = next(
                            (c for c in ["symbol", "代码", "code", "股票代码"] if c in df.columns),
                            None,
                        )
                        if code_col:
                            symbols = [
                                str(c).strip().lstrip("0").zfill(5)
                                for c in df[code_col].dropna().unique()
                                if str(c).strip()
                            ]
                            logger.info(f"港股列表: 从 {source_name} 获取到 {len(symbols)} 只")
                            return symbols
        except Exception as e:
            logger.warning(f"从 Provider 获取港股列表失败: {e}")

        # 3. 最后兜底：直接从数据库 distinct
        try:
            from app.core.database import get_mongo_db
            db = get_mongo_db()
            coll_name = get_collection_name("basic_info", "HK")
            symbols = await db[coll_name].distinct("symbol")
            if symbols:
                logger.info(f"港股列表: 从数据库 distinct 获取到 {len(symbols)} 只")
                return symbols
        except Exception as e:
            logger.warning(f"从数据库获取港股列表失败: {e}")

        logger.warning("港股列表: 所有获取方式均失败")
        return []


# ── 全局单例 ──────────────────────────────────────────────────────────

_hk_sync_service: Optional[HKSyncService] = None
_hk_sync_lock = asyncio.Lock()


async def get_hk_sync_service() -> HKSyncService:
    global _hk_sync_service
    if _hk_sync_service is not None:
        return _hk_sync_service
    async with _hk_sync_lock:
        if _hk_sync_service is None:
            _hk_sync_service = HKSyncService()
            await _hk_sync_service.initialize()
    return _hk_sync_service


# ── APScheduler 入口函数 ─────────────────────────────────────────────

async def run_hk_basic_info_sync(force_update: bool = False):
    service = await get_hk_sync_service()
    result = await service.sync_stock_basic_info(force_update=force_update)
    logger.info(f"港股基础信息同步完成: {result}")
    return result


async def run_hk_daily_quotes_sync(incremental: bool = True):
    service = await get_hk_sync_service()
    result = await service.sync_daily_quotes(incremental=incremental)
    logger.info(f"港股日线同步完成: {result}")
    return result


async def run_hk_status_check():
    service = await get_hk_sync_service()
    result = await service.run_status_check()
    logger.info(f"港股状态检查: {result}")
    return result
