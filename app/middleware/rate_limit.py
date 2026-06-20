"""
速率限制中间件
防止API滥用，实现用户级和端点级速率限制

故障策略（Redis 不可用时）：
- 敏感路径（登录/注册）：fail-closed，返回 503 防止暴力破解绕过限流
- 普通业务路径：fail-open，返回 429 风险较低时降级放行
"""

import asyncio
import time
import logging
from typing import Callable, Optional

from fastapi import Request, Response, HTTPException
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.redis_client import RedisKeys
from app.utils.time_utils import get_current_date

logger = logging.getLogger(__name__)

# 标记 Redis 是否可用，附带重试时间戳
_redis_available: Optional[bool] = None
_redis_last_check: float = 0
_REDIS_RETRY_INTERVAL = 10  # 缩短为 10 秒，配合自愈循环

# 敏感路径前缀：Redis 故障时必须 fail-closed
_SENSITIVE_PATH_PREFIXES = (
    "/api/auth/login",
    "/api/auth/register",
    "/api/auth/refresh",
)


def _is_sensitive_path(path: str) -> bool:
    """判断是否为敏感路径（鉴权/登录类，Redis 故障时必须拒绝）。"""
    normalized = path.rstrip("/")
    return any(normalized == p or normalized.startswith(p + "/") for p in _SENSITIVE_PATH_PREFIXES)


def _get_redis_service_safe():
    """安全获取 Redis 服务，Redis 不可用时返回 None（10 秒后自动重试）"""
    global _redis_available, _redis_last_check
    if _redis_available is False:
        if (time.time() - _redis_last_check) < _REDIS_RETRY_INTERVAL:
            return None
    try:
        from app.core.redis_client import get_redis_service
        service = get_redis_service()
        _redis_available = True
        return service
    except Exception as e:
        if _redis_available is None or _redis_available:
            logger.warning(f"⚠️ Redis 不可用，速率限制功能已降级: {e}")
        _redis_available = False
        _redis_last_check = time.time()
        return None


async def _redis_recovery_loop(stop_event: asyncio.Event):
    """后台协程：定期 ping Redis，恢复后立即清除不可用标记。

    默认 10 秒一次，避免被限流的合法请求在 Redis 恢复后仍被长时间阻挡。
    """
    global _redis_available, _redis_last_check
    while not stop_event.is_set():
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=_REDIS_RETRY_INTERVAL)
            return  # stop_event 被 set，退出
        except asyncio.TimeoutError:
            pass
        if _redis_available is False:
            try:
                from app.core.redis_client import get_redis_service
                service = get_redis_service()
                # RedisService 已实现 ping()，返回 True 表示恢复
                ok = await service.ping()
                if ok:
                    _redis_available = True
                    logger.info("✅ Redis 已恢复，速率限制功能恢复正常")
            except Exception as exc:
                logger.debug(f"Redis 恢复检查失败: {exc}")
                _redis_last_check = time.time()


# 全局自愈协程句柄（避免重复启动）
_recovery_task: Optional[asyncio.Task] = None
_recovery_stop_event: Optional[asyncio.Event] = None


def start_redis_recovery_loop():
    """启动 Redis 自愈协程（幂等）。"""
    global _recovery_task, _recovery_stop_event
    if _recovery_task is not None and not _recovery_task.done():
        return
    try:
        _recovery_stop_event = asyncio.Event()
        _recovery_task = asyncio.create_task(_redis_recovery_loop(_recovery_stop_event))
        logger.debug("Redis 自愈协程已启动")
    except RuntimeError:
        # 没有 event loop（启动早期）— 忽略，下次再调
        pass


def stop_redis_recovery_loop():
    """停止 Redis 自愈协程（应用关闭时调用）。"""
    global _recovery_task, _recovery_stop_event
    if _recovery_stop_event is not None:
        _recovery_stop_event.set()
    if _recovery_task is not None and not _recovery_task.done():
        _recovery_task.cancel()
    _recovery_task = None
    _recovery_stop_event = None


def _get_client_ip(request: Request) -> str:
    """获取客户端真实 IP，仅在可信代理后读取转发头"""
    client_host = request.client.host if request.client else "unknown"

    from app.core.config import settings
    trusted_proxies = {p.strip() for p in settings.TRUSTED_PROXIES.split(",") if p.strip()}
    if client_host in trusted_proxies:
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            return forwarded.split(",")[0].strip()
        real_ip = request.headers.get("x-real-ip")
        if real_ip:
            return real_ip.strip()

    return client_host


def _redis_unavailable_response(path: str) -> JSONResponse:
    """Redis 不可用且为敏感路径时的 503 响应。"""
    return JSONResponse(
        status_code=503,
        content={
            "error": {
                "code": "RATE_LIMIT_UNAVAILABLE",
                "message": "限流服务暂不可用，敏感操作已被拒绝，请稍后重试",
                "path": path,
            }
        },
    )


class RateLimitMiddleware(BaseHTTPMiddleware):
    """速率限制中间件"""

    def __init__(self, app, default_rate_limit: int = 100):
        super().__init__(app)
        self.default_rate_limit = default_rate_limit

        # 不同端点的速率限制配置
        self.endpoint_limits = {
            "/api/analysis/single": 10,      # 单股分析：每分钟10次
            "/api/analysis/batch": 5,        # 批量分析：每分钟5次
            "/api/screening/run": 20,         # 股票筛选：每分钟20次
            "/api/auth/login": 5,            # 登录：每分钟5次
            "/api/auth/register": 3,         # 注册：每分钟3次
        }

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # 跳过健康检查和静态资源
        if request.url.path.startswith(("/api/health", "/docs", "/redoc", "/openapi.json")):
            return await call_next(request)

        # 获取用户ID（如果已认证）
        user_id = getattr(request.state, "user_id", None)
        if not user_id:
            # 对于未认证用户，使用真实 IP 地址（支持代理头）
            user_id = f"ip:{_get_client_ip(request)}"

        # 检查速率限制
        try:
            blocked = await self.check_rate_limit(user_id, request.url.path)
            if blocked:
                return blocked
        except HTTPException:
            raise
        except Exception as exc:
            logger.error(f"速率限制检查失败: {exc}")
            # 兜底：敏感路径在异常时也 fail-closed
            if _is_sensitive_path(request.url.path):
                return _redis_unavailable_response(request.url.path)

        return await call_next(request)

    async def check_rate_limit(self, user_id: str, endpoint: str) -> Optional[JSONResponse]:
        """检查速率限制。

        Returns:
            None — 通过；
            JSONResponse — Redis 不可用且敏感路径时的 503 响应。
        """
        redis_service = _get_redis_service_safe()
        if redis_service is None:
            # Redis 故障：敏感路径必须 fail-closed
            if _is_sensitive_path(endpoint):
                logger.warning(
                    f"Redis 不可用，敏感路径拒绝访问: path={endpoint}, user={user_id}"
                )
                return _redis_unavailable_response(endpoint)
            return None  # 非敏感路径降级放行

        # 获取端点的速率限制（标准化路径：去除尾部斜杠）
        normalized_endpoint = endpoint.rstrip("/")
        rate_limit = self.endpoint_limits.get(normalized_endpoint, self.default_rate_limit)

        # 构建Redis键（使用标准化路径，确保尾部斜杠不影响计数）
        rate_key = RedisKeys.USER_RATE_LIMIT.format(
            user_id=user_id,
            endpoint=normalized_endpoint.replace("/", "_")
        )

        # 获取当前计数
        current_count = await redis_service.increment_with_ttl(rate_key, ttl=60)

        # 检查是否超过限制
        if current_count > rate_limit:
            logger.warning(
                f"速率限制触发 - 用户: {user_id}, "
                f"端点: {endpoint}, "
                f"当前计数: {current_count}, "
                f"限制: {rate_limit}"
            )

            raise HTTPException(
                status_code=429,
                detail={
                    "error": {
                        "code": "RATE_LIMIT_EXCEEDED",
                        "message": "请求过于频繁，请稍后重试",
                        "rate_limit": rate_limit,
                        "current_count": current_count,
                        "reset_time": 60
                    }
                }
            )

        logger.debug(
            f"速率限制检查通过 - 用户: {user_id}, "
            f"端点: {endpoint}, "
            f"当前计数: {current_count}/{rate_limit}"
        )
        return None


class QuotaMiddleware(BaseHTTPMiddleware):
    """每日配额中间件"""

    def __init__(self, app, daily_quota: int = 1000):
        super().__init__(app)
        self.daily_quota = daily_quota

        # 需要计入配额的端点
        self.quota_endpoints = {
            "/api/analysis/single",
            "/api/analysis/batch",
            "/api/screening/run"
        }

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # 只对需要配额的端点进行检查（标准化路径：去除尾部斜杠）
        if request.url.path.rstrip("/") not in self.quota_endpoints:
            return await call_next(request)

        # 获取用户ID
        user_id = getattr(request.state, "user_id", None)
        if not user_id:
            # 未认证用户不受配额限制
            return await call_next(request)

        # 检查每日配额
        try:
            blocked = await self.check_daily_quota(user_id)
            if blocked:
                return blocked
        except HTTPException:
            raise
        except Exception as exc:
            logger.error(f"配额检查失败: {exc}")

        return await call_next(request)

    async def check_daily_quota(self, user_id: str) -> Optional[JSONResponse]:
        """检查每日配额。

        配额类端点为业务操作（非敏感），Redis 故障时降级放行。
        """
        redis_service = _get_redis_service_safe()
        if redis_service is None:
            return None  # 非敏感路径降级放行

        # 获取今天的日期（配置时区）
        today = get_current_date()

        # 构建Redis键
        quota_key = RedisKeys.USER_DAILY_QUOTA.format(
            user_id=user_id,
            date=today
        )

        # 获取今日使用量
        current_usage = await redis_service.increment_with_ttl(quota_key, ttl=86400)  # 24小时TTL

        # 检查是否超过配额
        if current_usage > self.daily_quota:
            logger.warning(
                f"每日配额超限 - 用户: {user_id}, "
                f"今日使用: {current_usage}, "
                f"配额: {self.daily_quota}"
            )

            raise HTTPException(
                status_code=429,
                detail={
                    "error": {
                        "code": "DAILY_QUOTA_EXCEEDED",
                        "message": "今日配额已用完，请明天再试",
                        "daily_quota": self.daily_quota,
                        "current_usage": current_usage,
                        "reset_date": today
                    }
                }
            )

        logger.debug(
            f"配额检查通过 - 用户: {user_id}, "
            f"今日使用: {current_usage}/{self.daily_quota}"
        )
        return None
