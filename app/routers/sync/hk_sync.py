"""
港股同步路由（按需缓存模式）

港股数据采用按需获取 + MongoDB TTL 缓存模式，
不使用定时全量同步。提供数据源管理、缓存预热、进度查询、使用建议接口。
"""

import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from app.routers.auth_db import get_current_user
from app.core.response import ok, fail

logger = logging.getLogger("webapi")

router = APIRouter(prefix="/api/sync/hk", tags=["HK Sync"])

# 数据源描述映射
SOURCE_DESCRIPTIONS = {
    "akshare_hk": "AKShare港股数据源，提供港股基础信息和行情数据（免费，无需API Key）",
    "yfinance_hk": "Yahoo Finance港股数据源，提供基础信息和行情数据",
}

# 默认数据源优先级（回退用）
_DEFAULT_PRIORITY = {"akshare_hk": 10, "yfinance_hk": 5}

# adapter 名称 -> 数据库中 data_source_name 的映射
_ADAPTER_TO_DB_NAME = {
    "akshare_hk": "akshare",
    "yfinance_hk": "yahoo_finance",
}


class HKCacheWarmRequest(BaseModel):
    symbol: str = Field(..., description="港股代码，如 00700")
    force: bool = Field(False, description="是否强制刷新")


class HKBatchWarmRequest(BaseModel):
    symbols: List[str] = Field(..., description="港股代码列表")
    force: bool = Field(False, description="是否强制刷新")


class HKSourceTestRequest(BaseModel):
    source_name: Optional[str] = Field(None, description="指定测试的数据源，为空则测试全部")


# ==================== 数据源管理 ====================


@router.get("/sources/status")
async def get_hk_sources_status():
    """港股数据源状态（含优先级和描述）"""
    try:
        from app.data.config import get_source_priority
        from app.data.sources.hk.akshare_hk import get_akshare_hk_adapter
        from app.data.sources.hk.yfinance_hk import get_yfinance_hk_adapter

        priority_map = get_source_priority("HK")
        adapters = [
            ("akshare_hk", get_akshare_hk_adapter),
            ("yfinance_hk", get_yfinance_hk_adapter),
        ]
        result = []
        for name, factory in adapters:
            try:
                adapter = factory()
                available = adapter.provider.is_available()
            except Exception:
                available = False
            result.append({
                "name": name,
                "available": available,
                "priority": priority_map.get(_ADAPTER_TO_DB_NAME.get(name, name), _DEFAULT_PRIORITY.get(name, 0)),
                "description": SOURCE_DESCRIPTIONS.get(name, ""),
            })

        result.sort(key=lambda x: x["priority"], reverse=True)
        return ok(data=result)
    except Exception as e:
        logger.error(f"获取港股数据源状态失败: {e}")
        return ok(data=[], message=str(e))


@router.post("/sources/test")
async def test_hk_sources(
    request: HKSourceTestRequest,
    current_user: dict = Depends(get_current_user),
):
    """测试港股数据源连通性"""
    try:
        from app.data.sources.hk.akshare_hk import get_akshare_hk_adapter
        from app.data.sources.hk.yfinance_hk import get_yfinance_hk_adapter

        adapters = [
            ("akshare_hk", get_akshare_hk_adapter),
            ("yfinance_hk", get_yfinance_hk_adapter),
        ]

        if request.source_name:
            adapters = [(n, f) for n, f in adapters if n == request.source_name]

        test_results = []
        for name, factory in adapters:
            try:
                adapter = factory()
                available = adapter.provider.is_available()
                message = "连接成功" if available else "连接失败"
                # 端到端验证：尝试获取代表性股票
                if available:
                    try:
                        info = await adapter.provider.get_stock_basic_info("00700")
                        if info:
                            stock_name = info.get("name", "")
                            message = f"连接成功，成功获取腾讯控股({stock_name})数据"
                        else:
                            message = "连接成功但获取测试数据为空"
                    except Exception as e:
                        message = f"连接成功但数据获取异常: {e}"
                        available = False
            except Exception as e:
                available = False
                message = f"初始化失败: {e}"

            test_results.append({
                "name": name,
                "available": available,
                "message": message,
                "priority": _DEFAULT_PRIORITY.get(name, 0),
            })

        return ok(data={"test_results": test_results})
    except Exception as e:
        logger.error(f"港股数据源测试失败: {e}")
        return fail(message=str(e), data={"test_results": []})


# ==================== 缓存管理 ====================


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


@router.get("/cache/list")
async def list_hk_cached_stocks(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    current_user: dict = Depends(get_current_user),
):
    """获取港股已缓存股票列表（分页，按更新时间倒序）"""
    try:
        from app.worker.hk import get_hk_cache_service
        service = get_hk_cache_service()
        result = await service.list_cached_stocks(page, page_size)
        return ok(data=result)
    except Exception as e:
        logger.error(f"获取港股缓存列表失败: {e}")
        return ok(data={"records": [], "total": 0, "has_more": False}, message=str(e))


@router.post("/cache/warm")
async def warm_hk_cache(
    request: HKCacheWarmRequest,
    current_user: dict = Depends(get_current_user),
):
    """手动预热港股缓存（基础信息+行情）"""
    try:
        from app.worker.hk import get_hk_cache_service
        service = get_hk_cache_service()
        result = await service.warm_stock_with_quotes(request.symbol, request.force)
        if result["info_success"]:
            msg = f"港股 {request.symbol} 缓存预热成功（基础信息+{result['quotes_count']}条行情，来源: {result['source']}）"
            return ok(data=result, message=msg)
        else:
            return fail(message=f"港股 {request.symbol} 缓存预热失败", data=result)
    except Exception as e:
        logger.error(f"港股缓存预热失败: {e}")
        return fail(message=str(e))


@router.post("/cache/warm/batch")
async def batch_warm_hk_cache(
    request: HKBatchWarmRequest,
    current_user: dict = Depends(get_current_user),
):
    """批量预热港股缓存（后台执行）"""
    try:
        from app.worker.hk import get_hk_cache_service
        service = get_hk_cache_service()
        task_id = await service.warm_batch(request.symbols, request.force)
        return ok(data={"task_id": task_id, "total": len(request.symbols)}, message=f"批量预热任务已启动，共 {len(request.symbols)} 只股票")
    except Exception as e:
        logger.error(f"港股批量预热失败: {e}")
        return fail(message=str(e))


@router.get("/cache/warm/status")
async def get_hk_warm_status(
    current_user: dict = Depends(get_current_user),
):
    """查询港股批量预热进度"""
    try:
        from app.worker.hk import get_hk_cache_service
        service = get_hk_cache_service()
        status = service.get_batch_status()
        return ok(data=status)
    except Exception as e:
        logger.error(f"获取港股预热状态失败: {e}")
        return ok(data={"status": "idle"}, message=str(e))


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
        return fail(message=str(e))


# ==================== 使用建议 ====================


@router.get("/recommendations")
async def get_hk_recommendations():
    """港股数据源使用建议"""
    try:
        from app.data.config import get_enabled_sources, get_source_priority

        sources = get_enabled_sources("HK")
        priority_map = get_source_priority("HK")

        primary_source = None
        fallback_sources = []
        suggestions = []
        warnings = []

        source_display = {
            "akshare": "AKShare",
            "yfinance": "YFinance",
        }

        for i, src in enumerate(sources):
            display_name = source_display.get(src, src.upper())
            priority = priority_map.get(src, len(sources) - i)
            if i == 0:
                primary_source = {
                    "name": display_name,
                    "priority": priority,
                    "reason": "当前优先级最高的港股数据源" if src == "akshare" else "当前配置的首选港股数据源",
                }
            else:
                fallback_sources.append({"name": display_name, "priority": priority})

        suggestions = [
            "港股数据采用按需缓存模式（24小时有效期），不会自动定时同步",
            "建议在分析前先预热自选股缓存，确保数据新鲜",
            "AKShare 为免费数据源，无 API Key 限制，推荐优先使用",
            "YFinance 数据可能存在延迟，建议作为备用数据源",
            "缓存过期后会自动清理，无需手动维护",
        ]

        if "akshare" not in sources:
            warnings.append("未启用 AKShare 数据源，建议启用以获得免费的港股数据")

        if not sources:
            warnings.append("未配置任何港股数据源，请先在系统设置中配置")

        return ok(data={
            "primary_source": primary_source,
            "fallback_sources": fallback_sources,
            "suggestions": suggestions,
            "warnings": warnings,
            "env_config": {
                "description": "港股数据源无需额外环境变量，AKShare 和 YFinance 均为免费数据源",
            },
        })
    except Exception as e:
        logger.error(f"获取港股使用建议失败: {e}")
        return ok(data={"primary_source": None, "fallback_sources": [], "suggestions": [], "warnings": [str(e)]}, message=str(e))
