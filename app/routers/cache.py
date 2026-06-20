"""
缓存管理路由 — 委托 app.services.cache_service，不直接访问 storage 层。
"""

from fastapi import APIRouter, HTTPException, Depends, Query

from app.routers.auth_db import get_current_user, require_admin
from app.core.response import ok, safe_error_message
from app.utils.logging_manager import get_logger
from app.services.cache_service import CacheService

logger = get_logger(__name__)

router = APIRouter(prefix="/api/cache", tags=["Cache"])


@router.get("/stats")
async def get_cache_stats(current_user: dict = Depends(get_current_user)):
    """获取缓存统计信息。"""
    try:
        stats = await CacheService.get_instance().get_stats()
        logger.info(f"用户 {current_user['username']} 获取缓存统计")
        return ok(data=stats, message="获取缓存统计成功")
    except Exception as e:
        logger.error(f"获取缓存统计失败: {e}")
        raise HTTPException(
            status_code=500,
            detail=safe_error_message(e, "获取缓存统计失败"),
        )


@router.delete("/cleanup")
async def cleanup_old_cache(
    days: int = Query(7, ge=1, le=30, description="清理多少天前的缓存"),
    current_user: dict = Depends(get_current_user),
):
    """清理未设置 TTL 的过期缓存键。"""
    try:
        deleted = await CacheService.get_instance().cleanup_old_cache()
        logger.info(
            f"用户 {current_user['username']} 清理了 {days} 天前的缓存"
            f"（删除 {deleted} 键）"
        )
        return ok(
            data={"days": days, "deletedKeys": deleted},
            message=f"已清理 {days} 天前的缓存",
        )
    except Exception as e:
        logger.error(f"清理缓存失败: {e}")
        raise HTTPException(
            status_code=500,
            detail=safe_error_message(e, "清理缓存失败"),
        )


@router.delete("/clear")
async def clear_all_cache(current_user: dict = Depends(require_admin)):
    """清空所有缓存（业务前缀 Redis + 内存 TTLCache）。"""
    try:
        deleted = await CacheService.get_instance().clear_all()
        logger.warning(
            f"用户 {current_user['username']} 清空了所有缓存"
            f"（删除 {deleted} 键）"
        )
        return ok(data={"deletedKeys": deleted}, message="所有缓存已清空")
    except Exception as e:
        logger.error(f"清空缓存失败: {e}")
        raise HTTPException(
            status_code=500,
            detail=safe_error_message(e, "清空缓存失败"),
        )


@router.get("/details")
async def get_cache_details(
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=100, description="每页数量"),
    current_user: dict = Depends(get_current_user),
):
    """获取缓存详情列表。"""
    try:
        data = await CacheService.get_instance().list_details(page, page_size)
        logger.info(
            f"用户 {current_user['username']} 获取缓存详情 (页码: {page})"
        )
        return ok(data=data, message="获取缓存详情成功")
    except Exception as e:
        logger.error(f"获取缓存详情失败: {e}")
        raise HTTPException(
            status_code=500,
            detail=safe_error_message(e, "获取缓存详情失败"),
        )


@router.delete("/items/{key:path}")
async def delete_cache_item(
    key: str,
    current_user: dict = Depends(require_admin),
):
    """删除单个缓存条目（Redis + 内存）。"""
    try:
        service = CacheService.get_instance()
        try:
            existed, redis_deleted, memory_deleted = await service.delete_item(key)
        except PermissionError:
            logger.warning(
                f"用户 {current_user['username']} 试图删除系统内部缓存键: "
                f"{key[:32]}"
            )
            raise HTTPException(
                status_code=403,
                detail="禁止访问系统内部缓存键",
            )

        if not existed:
            logger.info(
                f"用户 {current_user['username']} 删除缓存键不存在: {key[:32]}"
            )
            return ok(
                data={"key": key, "existed": False},
                message="缓存键不存在",
            )

        logger.info(
            f"用户 {current_user['username']} 删除缓存键: {key[:32]}"
        )
        return ok(
            data={
                "key": key,
                "existed": True,
                "redis_deleted": redis_deleted,
                "memory_deleted": memory_deleted,
            },
            message="缓存项已删除",
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"删除缓存项失败: {e}")
        raise HTTPException(
            status_code=500,
            detail=safe_error_message(e, "删除缓存项失败"),
        )


def set_memory_cache(cache) -> None:
    """注册全局 TTLCache 实例（应用启动时调用）。

    保留为 router 暴露的入口，向后兼容现有 main.py 调用点；
    内部委托给 CacheService.register_memory_cache。
    """
    CacheService.register_memory_cache(cache)


def get_memory_cache():
    """获取已注册的 TTLCache 实例（向后兼容入口）。"""
    return CacheService.get_instance().get_memory_cache()
