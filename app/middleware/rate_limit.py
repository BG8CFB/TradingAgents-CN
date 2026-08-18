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

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.redis_client import RedisKeys
from app.utils.time_utils import get_current_date
from app.utils.request_utils import get_client_ip, extract_user_id_from_jwt

logger = logging.getLogger(__name__)

# 标记 Redis 是否可用，附带重试时间戳
_redis_available: Optional[bool] = None
_redis_last_check: float = 0
_REDIS_RETRY_INTERVAL = 10  # 缩短为 10 秒，配合自愈循环
# ping 成功后的信任窗口：窗口内跳过 ping，减少每请求延迟
_REDIS_TRUST_WINDOW = 30  # 秒
# 保护 _redis_available / _redis_last_check 读写的异步锁，防止请求协程与
# 后台自愈协程之间的 TOCTOU 竞态（检查与赋值之间被另一方修改）。
# 延迟创建：模块导入时不绑定事件循环，首次使用时在当前循环中创建。
_redis_state_lock: Optional[asyncio.Lock] = None


def _get_state_lock() -> asyncio.Lock:
    """延迟创建 asyncio.Lock，避免模块导入时绑定到尚未就绪的事件循环。

    线程安全说明（R11 核实结论）：
    本函数为普通同步函数，函数体内无 await。在 Python 单线程 asyncio 协程
    调度模型下，不含 await 的同步代码段是原子执行的——不会被其他协程抢占，
    因此 check-then-act 不存在竞态。所有调用方（_get_redis_service_safe、
    _redis_recovery_loop）均为 async 函数，运行在同一事件循环的同一线程中。
    APScheduler 使用 AsyncIOScheduler，定时任务也在同一事件循环中执行。
    """
    global _redis_state_lock
    if _redis_state_lock is None:
        _redis_state_lock = asyncio.Lock()
    return _redis_state_lock

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


async def _get_redis_service_safe():
    """安全获取 Redis 服务，Redis 不可用时返回 None（10 秒后自动重试）。

    使用 ``_redis_state_lock`` 保护 ``_redis_available`` / ``_redis_last_check``
    的读写，防止请求协程与后台自愈协程之间的 TOCTOU 竞态。

    当 ``_redis_available`` 为 True 时，做一次快速 ping（带 500ms 超时）
    验证连接是否真的可用。避免 Redis 客户端已初始化但连接断开时，
    每个请求都尝试一次失败的 Redis 操作而增加延迟。
    """
    global _redis_available, _redis_last_check
    async with _get_state_lock():
        if _redis_available is False:
            if (time.time() - _redis_last_check) < _REDIS_RETRY_INTERVAL:
                return None
            # 检查自愈协程是否在运行。若未运行（如启动时无事件循环），
            # 尝试在此处重新启动，确保 Redis 恢复后能自动恢复限流功能。
            if _recovery_task is None or _recovery_task.done():
                _redis_available = None  # 重置状态，允许下方 ping 重新判定
                start_redis_recovery_loop()

    try:
        from app.core.redis_client import get_redis_service
        service = get_redis_service()

        # 快速 ping 验证连接可达性（仅当状态为 True 或 None 时）
        # 避免客户端已初始化但连接断开时每个请求都走失败路径。
        # 信任窗口优化：ping 成功后 30 秒内跳过 ping，减少每请求延迟。
        # Redis 实际不可用时，操作本身会抛异常被外层 catch。
        async with _get_state_lock():
            within_trust = (time.time() - _redis_last_check) < _REDIS_TRUST_WINDOW
            need_ping = _redis_available is not False and not within_trust
        if need_ping:
            try:
                ok = await asyncio.wait_for(service.ping(), timeout=0.5)
                if not ok:
                    raise ConnectionError("ping returned False")
            except Exception:
                async with _get_state_lock():
                    if _redis_available is None or _redis_available:
                        logger.warning("⚠️ Redis ping 超时或失败，速率限制功能已降级")
                    _redis_available = False
                    _redis_last_check = time.time()
                return None

        async with _get_state_lock():
            _redis_available = True
            _redis_last_check = time.time()  # 更新信任窗口起点
        return service
    except Exception as e:
        async with _get_state_lock():
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
        async with _get_state_lock():
            available = _redis_available
        if available is False:
            try:
                from app.core.redis_client import get_redis_service
                service = get_redis_service()
                # RedisService 已实现 ping()，返回 True 表示恢复
                ok = await service.ping()
                if ok:
                    async with _get_state_lock():
                        _redis_available = True
                    logger.info("✅ Redis 已恢复，速率限制功能恢复正常")
            except RuntimeError as exc:
                # RuntimeError 通常表示 Redis 客户端尚未初始化（而非连接中断）
                logger.warning(f"Redis 客户端未初始化，自愈循环等待 init_database(): {exc}")
                async with _get_state_lock():
                    _redis_available = False
                    _redis_last_check = time.time()
            except Exception as exc:
                logger.debug(f"Redis 恢复检查失败: {exc}")
                # 恢复检查失败说明 Redis 仍不可用，确保状态标记一致
                async with _get_state_lock():
                    _redis_available = False
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
        # 没有 event loop（启动早期）— 记录 warning 便于运维排查，
        # 下次调用时重试。若自愈协程始终未启动，Redis 故障后无法自动恢复。
        logger.warning("Redis 自愈协程未启动：当前无事件循环，将在下次调用时重试")


def stop_redis_recovery_loop():
    """停止 Redis 自愈协程（应用关闭时调用）。"""
    global _recovery_task, _recovery_stop_event
    if _recovery_stop_event is not None:
        _recovery_stop_event.set()
    if _recovery_task is not None and not _recovery_task.done():
        _recovery_task.cancel()
    _recovery_task = None
    _recovery_stop_event = None


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

        # 获取用户ID（已认证用户从 JWT sub 字段获取，未认证用 IP）
        # 中间件在路由处理器之前执行，request.state.user_id 尚未由
        # Depends(get_current_user) 写入。直接从 Authorization header
        # 解析 JWT，与 OperationLogMiddleware 的策略一致。
        user_id = extract_user_id_from_jwt(request)
        if not user_id:
            # 对于未认证用户，使用真实 IP 地址（支持代理头）
            user_id = f"ip:{get_client_ip(request)}"

        # 检查速率限制
        try:
            blocked = await self.check_rate_limit(user_id, request.url.path)
            if blocked:
                return blocked
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
        redis_service = await _get_redis_service_safe()
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

        # 获取当前计数（先 INCR 后检查）
        # 设计选择：速率限制场景下先递增再检查是合理的——每次请求（含被拒绝的
        # 429）都消耗一个计数槽，可防止攻击者通过大量请求试探限流边界。
        # 这与 QuotaMiddleware 的"已超限时不递增"策略不同：配额是有限资源，
        # 被拒绝的请求不应消耗配额；而速率限制是滑动窗口，计数会自动过期。
        current_count = await redis_service.increment_with_ttl(rate_key, ttl=60)

        # 检查是否超过限制
        if current_count > rate_limit:
            logger.warning(
                f"速率限制触发 - 用户: {user_id}, "
                f"端点: {endpoint}, "
                f"当前计数: {current_count}, "
                f"限制: {rate_limit}"
            )

            return JSONResponse(
                status_code=429,
                content={
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

        # 获取用户ID（从 JWT 解析，中间件层早于路由认证）
        user_id = extract_user_id_from_jwt(request)
        if not user_id:
            # 未认证用户不受配额限制。
            # 配额端点（analysis/single、analysis/batch、screening/run）在
            # 路由层均使用 Depends(get_current_user) 强制认证，未认证请求
            # 不会到达 call_next 之后的业务逻辑。此分支仅是防御性短路。
            return await call_next(request)

        # 检查每日配额
        try:
            blocked = await self.check_daily_quota(user_id)
            if blocked:
                return blocked
        except Exception as exc:
            logger.error(f"配额检查失败: {exc}")

        return await call_next(request)

    async def check_daily_quota(self, user_id: str) -> Optional[JSONResponse]:
        """检查每日配额。

        配额类端点为业务操作（非敏感），Redis 故障时降级放行。
        使用 Lua 脚本实现原子性检查+递增，避免 TOCTOU 竞态。

        Returns:
            None — 通过；
            JSONResponse — 配额超限时的 429 响应。
        """
        redis_service = await _get_redis_service_safe()
        if redis_service is None:
            return None  # 非敏感路径降级放行

        # 获取今天的日期（配置时区）
        today = get_current_date()

        # 构建Redis键
        quota_key = RedisKeys.USER_DAILY_QUOTA.format(
            user_id=user_id,
            date=today
        )

        # 原子性检查+递增：Lua 脚本保证"已超限时不递增，未超限时递增"的语义
        # 避免先前 GET→INCR 两步操作中的 TOCTOU 竞态
        try:
            result = await redis_service.check_and_increment_quota(
                quota_key, max_quota=self.daily_quota, ttl=86400
            )
        except Exception as exc:
            logger.error(f"原子配额检查失败: {exc}")
            return None  # 降级放行

        if not result["allowed"]:
            current_usage = result["current"]
            logger.warning(
                f"每日配额超限 - 用户: {user_id}, "
                f"今日使用: {current_usage}, "
                f"配额: {self.daily_quota}"
            )

            return JSONResponse(
                status_code=429,
                content={
                    "error": {
                        "code": "DAILY_QUOTA_EXCEEDED",
                        "message": "今日配额已用完，请明天再试",
                        "daily_quota": self.daily_quota,
                        "current_usage": current_usage,
                        "reset_date": today
                    }
                }
            )

        new_usage = result["current"]
        logger.debug(
            f"配额检查通过 - 用户: {user_id}, "
            f"今日使用: {new_usage}/{self.daily_quota}"
        )
        return None
