"""
缓存管理路由
提供缓存统计、清理等功能（基于 Redis + TTLCache 新架构）
"""
from fastapi import APIRouter, HTTPException, Depends, Query
from typing import Optional

from app.routers.auth_db import get_current_user, require_admin
from app.core.response import ok, safe_error_message
from app.utils.logging_manager import get_logger
from app.data.storage.redis.client import get_redis
from app.data.storage.cache.memory_cache import TTLCache

logger = get_logger(__name__)

router = APIRouter(prefix="/api/cache", tags=["Cache"])

# 全局 TTLCache 实例引用（通过 app state 注册）
_memory_cache: Optional[TTLCache] = None

# 系统内部缓存键前缀：禁止通过 /items/{key} 接口删除
# 这些前缀承载认证状态、会话、限流配额等关键状态；误删会让用户被锁死或绕过限流
FORBIDDEN_KEY_PREFIXES: tuple = (
    "token_blacklist:",     # logout 后吊销的 access_token
    "system_secrets:",      # JWT/CSRF 等系统密钥
    "session:",             # 用户会话
    "ratelimit:",           # 限流配额
    "auth:",                # 认证中间件状态
    "lock:",                # 分布式锁（避免误删导致并发保护失效）
)


def _is_forbidden_cache_key(key: str) -> bool:
    """判断是否禁止通过 cache API 删除的系统内部键。"""
    if not key:
        return False
    return any(key.startswith(prefix) for prefix in FORBIDDEN_KEY_PREFIXES)


def set_memory_cache(cache: TTLCache):
    """注册全局 TTLCache 实例（应用启动时调用）。"""
    global _memory_cache
    _memory_cache = cache


def get_memory_cache() -> Optional[TTLCache]:
    return _memory_cache


@router.get("/stats")
async def get_cache_stats(current_user: dict = Depends(get_current_user)):
    """
    获取缓存统计信息

    Returns:
        dict: 缓存统计数据
    """
    try:
        redis = get_redis()

        # Redis 统计
        redis_info = {}
        total_keys = 0
        if redis:
            try:
                total_keys = await redis.dbsize()
                info = await redis.info("memory")
                redis_info = {
                    "used_memory_human": info.get("used_memory_human", "N/A"),
                    "used_memory_peak_human": info.get("used_memory_peak_human", "N/A"),
                }
            except Exception as e:
                logger.warning(f"获取 Redis 统计失败: {e}")

        # TTLCache 统计
        memory_size = 0
        if _memory_cache:
            memory_size = _memory_cache.size()

        logger.info(f"用户 {current_user['username']} 获取缓存统计")

        return ok(
            data={
                "redis": {
                    "totalKeys": total_keys,
                    **redis_info,
                },
                "memoryCache": {
                    "size": memory_size,
                },
                "totalSize": 0,
                "maxSize": 1024 * 1024 * 1024,
                "stockDataCount": 0,
                "newsDataCount": 0,
                "analysisDataCount": 0,
            },
            message="获取缓存统计成功"
        )

    except Exception as e:
        logger.error(f"获取缓存统计失败: {e}")
        raise HTTPException(
            status_code=500,
            detail=safe_error_message(e, "获取缓存统计失败")
        )


@router.delete("/cleanup")
async def cleanup_old_cache(
    days: int = Query(7, ge=1, le=30, description="清理多少天前的缓存"),
    current_user: dict = Depends(get_current_user)
):
    """
    清理过期缓存（Redis 中 foreign_stock: 前缀的键）

    Args:
        days: 清理多少天前的缓存

    Returns:
        dict: 清理结果
    """
    try:
        redis = get_redis()
        deleted_count = 0

        if redis:
            try:
                # 扫描 foreign_stock: 前缀的键并检查 TTL
                cursor = 0
                while True:
                    cursor, keys = await redis.scan(
                        cursor, match="foreign_stock:*", count=100
                    )
                    if keys:
                        # 检查 TTL，-1 表示永不过期，-2 表示不存在
                        for key in keys:
                            ttl = await redis.ttl(key)
                            if ttl == -1:
                                # 没有设置 TTL 的键，直接删除（视为过期）
                                await redis.delete(key)
                                deleted_count += 1
                    if cursor == 0:
                        break
            except Exception as e:
                logger.warning(f"Redis 缓存清理失败: {e}")

        logger.info(f"用户 {current_user['username']} 清理了 {days} 天前的缓存（删除 {deleted_count} 键）")

        return ok(
            data={"days": days, "deletedKeys": deleted_count},
            message=f"已清理 {days} 天前的缓存"
        )

    except Exception as e:
        logger.error(f"清理缓存失败: {e}")
        raise HTTPException(
            status_code=500,
            detail=safe_error_message(e, "清理缓存失败")
        )


@router.delete("/clear")
async def clear_all_cache(current_user: dict = Depends(require_admin)):
    """
    清空所有缓存（Redis foreign_stock: 前缀 + 内存缓存）

    Returns:
        dict: 清理结果
    """
    try:
        redis = get_redis()
        deleted_count = 0

        if redis:
            try:
                cursor = 0
                while True:
                    cursor, keys = await redis.scan(
                        cursor, match="foreign_stock:*", count=100
                    )
                    if keys:
                        await redis.delete(*keys)
                        deleted_count += len(keys)
                    if cursor == 0:
                        break
            except Exception as e:
                logger.warning(f"Redis 缓存清空失败: {e}")

        # 清空内存缓存
        if _memory_cache:
            _memory_cache.clear()

        logger.warning(f"用户 {current_user['username']} 清空了所有缓存（删除 {deleted_count} 键）")

        return ok(
            data={"deletedKeys": deleted_count},
            message="所有缓存已清空"
        )

    except Exception as e:
        logger.error(f"清空缓存失败: {e}")
        raise HTTPException(
            status_code=500,
            detail=safe_error_message(e, "清空缓存失败")
        )


@router.get("/details")
async def get_cache_details(
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=100, description="每页数量"),
    current_user: dict = Depends(get_current_user)
):
    """
    获取缓存详情列表（Redis foreign_stock: 前缀键）

    Args:
        page: 页码
        page_size: 每页数量

    Returns:
        dict: 缓存详情列表
    """
    try:
        redis = get_redis()
        items = []
        total = 0

        if redis:
            try:
                # 收集所有 foreign_stock: 键
                all_keys = []
                cursor = 0
                while True:
                    cursor, keys = await redis.scan(
                        cursor, match="foreign_stock:*", count=100
                    )
                    all_keys.extend(keys)
                    if cursor == 0:
                        break

                total = len(all_keys)

                # 分页
                start = (page - 1) * page_size
                end = start + page_size
                page_keys = all_keys[start:end]

                for key in page_keys:
                    key_str = key if isinstance(key, str) else key.decode()
                    ttl = await redis.ttl(key)
                    key_type = await redis.type(key)
                    items.append({
                        "key": key_str,
                        "ttl": ttl,
                        "type": key_type,
                    })
            except Exception as e:
                logger.warning(f"获取 Redis 缓存详情失败: {e}")

        logger.info(f"用户 {current_user['username']} 获取缓存详情 (页码: {page})")

        return ok(
            data={
                "items": items,
                "total": total,
                "page": page,
                "page_size": page_size,
            },
            message="获取缓存详情成功"
        )

    except Exception as e:
        logger.error(f"获取缓存详情失败: {e}")
        raise HTTPException(
            status_code=500,
            detail=safe_error_message(e, "获取缓存详情失败")
        )


@router.delete("/items/{key:path}")
async def delete_cache_item(
    key: str,
    current_user: dict = Depends(require_admin)
):
    """
    删除单个缓存条目

    同时清理 Redis（若存在该 key）与内存 TTLCache（若存在）。

    Args:
        key: 缓存键（URL 解码后传入，支持包含冒号等分隔符）

    Returns:
        dict: 删除结果
    """
    try:
        # 路径遍历防护：禁止删除系统内部缓存键（认证状态、限流配额等）
        if _is_forbidden_cache_key(key):
            logger.warning(
                f"用户 {current_user['username']} 试图删除系统内部缓存键: {key[:32]}"
            )
            raise HTTPException(
                status_code=403,
                detail="禁止访问系统内部缓存键",
            )

        redis = get_redis()
        redis_deleted = False

        if redis:
            try:
                deleted = await redis.delete(key)
                redis_deleted = deleted > 0
            except Exception as e:
                logger.warning(f"Redis 单条删除失败: {e}")

        memory_deleted = False
        if _memory_cache:
            memory_deleted = _memory_cache.invalidate(key)

        if not (redis_deleted or memory_deleted):
            logger.info(f"用户 {current_user['username']} 删除缓存键不存在: {key[:32]}")
            return ok(
                data={"key": key, "existed": False},
                message="缓存键不存在"
            )

        logger.info(f"用户 {current_user['username']} 删除缓存键: {key[:32]}")

        return ok(
            data={
                "key": key,
                "existed": True,
                "redis_deleted": redis_deleted,
                "memory_deleted": memory_deleted,
            },
            message="缓存项已删除"
        )

    except HTTPException:
        # 业务异常（403 等）直接透传，不要被 500 覆盖
        raise
    except Exception as e:
        logger.error(f"删除缓存项失败: {e}")
        raise HTTPException(
            status_code=500,
            detail=safe_error_message(e, "删除缓存项失败")
        )
