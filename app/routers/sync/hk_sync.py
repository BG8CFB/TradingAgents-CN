"""
港股同步路由（按需缓存模式）

港股数据采用按需获取 + MongoDB TTL 缓存模式，
不使用定时全量同步。提供缓存预热、状态查询和清理接口。
"""

import logging

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.routers.auth_db import get_current_user
from app.core.response import ok

logger = logging.getLogger("webapi")

router = APIRouter(prefix="/api/sync/hk", tags=["HK Sync"])


class HKCacheWarmRequest(BaseModel):
    symbol: str = Field(..., description="港股代码，如 00700")
    force: bool = Field(False, description="是否强制刷新")


@router.get("/sources/status")
async def get_hk_sources_status():
    """港股数据源状态"""
    try:
        from app.data.sources.hk.akshare_hk import get_akshare_hk_adapter
        from app.data.sources.hk.yfinance_hk import get_yfinance_hk_adapter

        adapters = [
            ("akshare_hk", get_akshare_hk_adapter),
            ("yfinance_hk", get_yfinance_hk_adapter),
        ]
        result = []
        for name, factory in adapters:
            try:
                adapter = factory()
                available = adapter.provider.is_available()
                result.append({"name": name, "available": available})
            except Exception:
                result.append({"name": name, "available": False})
        return ok(data=result)
    except Exception as e:
        logger.error(f"获取港股数据源状态失败: {e}")
        return ok(data=[], message=str(e))


@router.get("/cache/stats")
async def get_hk_cache_stats():
    """港股缓存统计"""
    try:
        from app.worker.hk import get_hk_cache_service
        service = get_hk_cache_service()
        stats = await service.get_cache_stats()
        return ok(data=stats)
    except Exception as e:
        logger.error(f"获取港股缓存统计失败: {e}")
        return ok(data={}, message=str(e))


@router.post("/cache/warm")
async def warm_hk_cache(
    request: HKCacheWarmRequest,
    current_user: dict = Depends(get_current_user),
):
    """手动预热港股缓存"""
    try:
        from app.worker.hk import get_hk_cache_service
        service = get_hk_cache_service()
        result = (
            await service.refresh_cache(request.symbol)
            if request.force
            else await service.get_stock_info(request.symbol)
        )
        if result:
            action = "刷新" if request.force else "预热"
            return ok(data=result, message=f"港股 {request.symbol} 缓存已{action}")
        else:
            return ok(message=f"港股 {request.symbol} 缓存处理失败", success=False)
    except Exception as e:
        logger.error(f"港股缓存预热失败: {e}")
        return ok(message=str(e), success=False)


@router.delete("/cache")
async def clear_hk_cache(
    current_user: dict = Depends(get_current_user),
):
    """清理港股过期缓存"""
    try:
        from app.worker.hk import get_hk_cache_service

        service = get_hk_cache_service()
        result = await service.clear_expired_cache()
        return ok(data=result, message=f"港股缓存清理完成，删除 {result['deleted_count']} 条过期记录")
    except Exception as e:
        logger.error(f"港股缓存清理失败: {e}")
        return ok(message=str(e), success=False)
