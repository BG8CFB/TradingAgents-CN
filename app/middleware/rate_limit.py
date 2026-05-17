"""
速率限制中间件
防止API滥用，实现用户级和端点级速率限制
"""

from fastapi import Request, Response, HTTPException
from starlette.middleware.base import BaseHTTPMiddleware
import logging
from typing import Callable, Dict, Optional
from app.core.redis_client import RedisKeys
from app.utils.time_utils import get_current_date

logger = logging.getLogger(__name__)

# 标记 Redis 是否可用，避免每次请求都重复报错
_redis_available: Optional[bool] = None


def _get_redis_service_safe():
    """安全获取 Redis 服务，Redis 不可用时返回 None"""
    global _redis_available
    if _redis_available is False:
        return None
    try:
        from app.core.redis_client import get_redis_service
        service = get_redis_service()
        _redis_available = True
        return service
    except Exception:
        if _redis_available is None:
            logger.warning("⚠️ Redis 不可用，速率限制功能已禁用")
        _redis_available = False
        return None


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


class RateLimitMiddleware(BaseHTTPMiddleware):
    """速率限制中间件"""

    def __init__(self, app, default_rate_limit: int = 100):
        super().__init__(app)
        self.default_rate_limit = default_rate_limit

        # 不同端点的速率限制配置
        self.endpoint_limits = {
            "/api/analysis/single": 10,      # 单股分析：每分钟10次
            "/api/analysis/batch": 5,        # 批量分析：每分钟5次
            "/api/screening/filter": 20,     # 股票筛选：每分钟20次
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
            await self.check_rate_limit(user_id, request.url.path)
        except HTTPException:
            raise
        except Exception as exc:
            logger.error(f"速率限制检查失败: {exc}")
            # 如果Redis不可用，允许请求通过

        return await call_next(request)
    
    async def check_rate_limit(self, user_id: str, endpoint: str):
        """检查速率限制"""
        redis_service = _get_redis_service_safe()
        if redis_service is None:
            return  # Redis 不可用，跳过限流
        
        # 获取端点的速率限制（标准化路径：去除尾部斜杠）
        normalized_endpoint = endpoint.rstrip("/")
        rate_limit = self.endpoint_limits.get(normalized_endpoint, self.default_rate_limit)
        
        # 构建Redis键
        rate_key = RedisKeys.USER_RATE_LIMIT.format(
            user_id=user_id,
            endpoint=endpoint.replace("/", "_")
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
                        "message": f"请求过于频繁，请稍后重试",
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


class QuotaMiddleware(BaseHTTPMiddleware):
    """每日配额中间件"""
    
    def __init__(self, app, daily_quota: int = 1000):
        super().__init__(app)
        self.daily_quota = daily_quota
        
        # 需要计入配额的端点
        self.quota_endpoints = {
            "/api/analysis/single",
            "/api/analysis/batch",
            "/api/screening/filter"
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
            await self.check_daily_quota(user_id)
        except HTTPException:
            raise
        except Exception as exc:
            logger.error(f"配额检查失败: {exc}")
            # 如果Redis不可用，允许请求通过
        
        return await call_next(request)
    
    async def check_daily_quota(self, user_id: str):
        """检查每日配额"""
        redis_service = _get_redis_service_safe()
        if redis_service is None:
            return  # Redis 不可用，跳过配额检查

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
