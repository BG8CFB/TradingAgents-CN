"""
操作日志记录中间件
自动记录用户的API操作日志

设计要点：
- 主路径：解析 Authorization header 中的 JWT（零额外请求开销）
- 记录异步化（fire-and-forget），不阻塞响应；DB 异常时降级同步写入
- 后台任务不持有 Request 对象，仅持有轻量 RequestSnapshot，避免高并发
  场景下未完成的日志任务把 Request / Response / ASGI scope 全部"钉住"
  （这些对象背后还连着 transport、缓存区等，是典型的隐式内存堆积）
"""

import time
import logging
from dataclasses import dataclass
from typing import Optional, Dict, Any
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware

from app.services.operation_log_service import log_operation
from app.models.operation_log import ActionType
from app.utils.secret_masking import mask_query_params

logger = logging.getLogger("webapi")

# 全局开关：是否启用操作日志记录（可由系统设置动态控制）
OPLOG_ENABLED: bool = True


@dataclass(frozen=True, eq=True)
class RequestSnapshot:
    """请求快照：仅持有日志任务需要的字段。

    ``Request`` 对象在 ASGI 协议下持有 transport、scope、headers 缓存等
    大量上游资源；后台日志任务若持引用，会让这些资源在任务完成前无法释放。
    快照化后只保留几 KB 字符串 + tuple，无上游对象依赖。

    注：``query_params`` 用 ``tuple[tuple[str, str], ...]`` 而非 dict，
    使得整个 snapshot 在需要时可哈希；同时保证日志回放时参数顺序稳定。
    """
    method: str
    path: str
    query_params: Optional[tuple] = None  # tuple of (key, value) pairs


def _get_client_ip_from_request(request: Request) -> str:
    """获取客户端真实 IP 地址（仅信任来自受信代理的代理头）"""
    direct_ip = request.client.host if request.client else "unknown"

    # 仅当直连 IP 来自受信代理时，才读取代理头
    from app.core.config import settings
    trusted = tuple(p.strip() for p in settings.TRUSTED_PROXIES.split(",") if p.strip())
    if direct_ip in trusted:
        forwarded_for = request.headers.get("x-forwarded-for")
        if forwarded_for:
            return forwarded_for.split(",")[0].strip()
        real_ip = request.headers.get("x-real-ip")
        if real_ip:
            return real_ip

    return direct_ip

def set_operation_log_enabled(flag: bool) -> None:
    global OPLOG_ENABLED
    OPLOG_ENABLED = bool(flag)



class OperationLogMiddleware(BaseHTTPMiddleware):
    """操作日志记录中间件"""

    def __init__(self, app, skip_paths: Optional[list] = None):
        super().__init__(app)
        # 跳过记录日志的路径
        self.skip_paths = skip_paths or [
            "/health",
            "/healthz",
            "/readyz",
            "/favicon.ico",
            "/docs",
            "/redoc",
            "/openapi.json",
            "/api/stream/",  # SSE流不记录
            "/api/system/logs/",  # 操作日志API本身不记录
        ]

        # 路径到操作类型的映射
        self.path_action_mapping = {
            "/api/analysis/": ActionType.STOCK_ANALYSIS,
            "/api/screening/": ActionType.SCREENING,
            "/api/config/": ActionType.CONFIG_MANAGEMENT,
            "/api/system/database/": ActionType.DATABASE_OPERATION,
            "/api/auth/login": ActionType.USER_LOGIN,
            "/api/auth/logout": ActionType.USER_LOGOUT,
            "/api/auth/change-password": ActionType.USER_MANAGEMENT,  # 🔧 添加修改密码操作类型
            "/api/reports/": ActionType.REPORT_GENERATION,
        }

    async def dispatch(self, request: Request, call_next):
        # 检查是否需要跳过记录
        if self._should_skip_logging(request):
            return await call_next(request)

        # 记录开始时间
        start_time = time.time()

        # 获取请求信息
        method = request.method
        path = request.url.path
        ip_address = self._get_client_ip(request)
        user_agent = request.headers.get("user-agent", "")

        # 提前快照化 query_params：避免后台任务持 Request 引用
        # （dispatch 完成后 Request 对象会被回收，但 _log_operation 异步延续到
        # 后台执行，若直接传 request 会拖住整个对象树）
        # query_params 转 tuple 让整个 snapshot 可哈希、可比较
        raw_qp = list(request.query_params.items()) if request.query_params else None
        snapshot = RequestSnapshot(
            method=method,
            path=path,
            query_params=tuple(raw_qp) if raw_qp else None,
        )

        # 获取用户信息（如果已认证）
        user_info = await self._get_user_info(request)

        # 处理请求
        try:
            response = await call_next(request)
        except Exception as exc:
            duration_ms = int((time.time() - start_time) * 1000)
            if user_info:
                # 异常路径同步写入，避免遗漏关键错误日志
                # query_params 同样需要脱敏：异常路径也可能携带 password/token 等
                from app.utils.secret_masking import mask_query_params
                masked_qp = (
                    dict(mask_query_params(list(snapshot.query_params)))
                    if snapshot.query_params else None
                )
                try:
                    await log_operation(
                        user_id=str(user_info.get("id", "")),
                        username=user_info.get("username", "unknown"),
                        action_type=ActionType.API_ACCESS,
                        action=f"{snapshot.method} {snapshot.path}",
                        details={
                            "error": str(exc),
                            "query_params": masked_qp,
                        },
                        success=False,
                        duration_ms=duration_ms,
                        ip_address=ip_address,
                        user_agent=user_agent
                    )
                except Exception as e:
                    logger.debug(f"记录错误操作日志失败: {e}")
            raise

        # 计算耗时
        duration_ms = int((time.time() - start_time) * 1000)

        # 异步记录操作日志（fire-and-forget，不阻塞响应）
        # 通过 task_registry 注册，确保 shutdown 时等待完成
        if user_info:
            try:
                from app.core.task_registry import task_registry
                task_registry.register(
                    self._log_operation(
                        user_info=user_info,
                        snapshot=snapshot,
                        response_status=response.status_code,
                        duration_ms=duration_ms,
                        ip_address=ip_address,
                        user_agent=user_agent,
                    ),
                    name="oplog",
                    critical=True,
                )
            except Exception as e:
                # create_task 失败（极少见），降级同步
                logger.error(f"调度操作日志失败，降级同步: {e}")
                try:
                    await self._log_operation(
                        user_info=user_info,
                        snapshot=snapshot,
                        response_status=response.status_code,
                        duration_ms=duration_ms,
                        ip_address=ip_address,
                        user_agent=user_agent,
                    )
                except Exception as fallback_exc:
                    logger.error(f"记录操作日志失败（同步降级）: {fallback_exc}")

        return response

    def _should_skip_logging(self, request: Request) -> bool:
        """判断是否应该跳过日志记录"""
        # 全局关闭时直接跳过
        if not OPLOG_ENABLED:
            return True

        path = request.url.path

        # 检查跳过路径
        for skip_path in self.skip_paths:
            if path.startswith(skip_path):
                return True

        # 只记录API请求
        if not path.startswith("/api/"):
            return True

        # 只记录特定HTTP方法
        if request.method not in ["POST", "PUT", "DELETE", "PATCH"]:
            return True

        return False

    def _get_client_ip(self, request: Request) -> str:
        """获取客户端IP地址"""
        return _get_client_ip_from_request(request)

    async def _get_user_info(self, request: Request) -> Optional[Dict[str, Any]]:
        """获取用户信息：从 Authorization header 解析 JWT。

        中间件在路由前执行，无法依赖 get_current_user 写入的 request.state.user
        （那是路由解析时才填的）。所以这里直接走 JWT 解析作为唯一路径。
        """
        return await self._parse_jwt_user(request)

    async def _parse_jwt_user(self, request: Request) -> Optional[Dict[str, Any]]:
        """从 Authorization header 解析 JWT Token 获取用户信息。"""
        try:
            auth_header = request.headers.get("authorization", "")
            if not auth_header.startswith("Bearer "):
                return None

            token = auth_header[7:]
            if not token:
                return None

            import jwt
            from app.core.config import settings

            payload = jwt.decode(
                token,
                settings.JWT_SECRET,
                algorithms=[settings.JWT_ALGORITHM],
                options={"verify_exp": True},
            )

            # JWT sub 字段即用户名（create_access_token 时 sub=username）
            username = payload.get("sub", "")
            return {
                "id": username,
                "username": username or "unknown",
                "role": "admin" if payload.get("is_admin") else "user",
            }
        except jwt.ExpiredSignatureError:
            return None
        except jwt.InvalidTokenError:
            return None
        except Exception as e:
            logger.debug(f"JWT token 解析失败: {e}")
            return None

    def _get_action_type(self, path: str) -> str:
        """根据路径获取操作类型"""
        for path_prefix, action_type in self.path_action_mapping.items():
            if path.startswith(path_prefix):
                return action_type

        return ActionType.SYSTEM_SETTINGS  # 默认类型

    def _get_action_description(self, method: str, path: str) -> str:
        """生成操作描述"""
        # 基础描述
        action_map = {
            "POST": "创建",
            "PUT": "更新",
            "PATCH": "修改",
            "DELETE": "删除"
        }

        action_verb = action_map.get(method, method)

        # 根据路径生成更具体的描述
        if "/analysis/" in path:
            if "single" in path:
                return f"{action_verb}单股分析任务"
            elif "batch" in path:
                return f"{action_verb}批量分析任务"
            else:
                return f"{action_verb}分析任务"

        elif "/screening/" in path:
            return f"{action_verb}股票筛选"

        elif "/config/" in path:
            if "llm" in path:
                return f"{action_verb}大模型配置"
            elif "datasource" in path:
                return f"{action_verb}数据源配置"
            else:
                return f"{action_verb}系统配置"

        elif "/database/" in path:
            if "backup" in path:
                return f"{action_verb}数据库备份"
            elif "cleanup" in path:
                return f"{action_verb}数据库清理"
            else:
                return f"{action_verb}数据库操作"

        elif "/auth/" in path:
            if "login" in path:
                return "用户登录"
            elif "logout" in path:
                return "用户登出"
            elif "change-password" in path:
                return "修改密码"
            else:
                return f"{action_verb}认证操作"

        else:
            return f"{action_verb} {path}"

    async def _log_operation(
        self,
        user_info: Dict[str, Any],
        snapshot: RequestSnapshot,
        response_status: int,
        duration_ms: int,
        ip_address: str,
        user_agent: str,
    ):
        """记录操作日志（后台任务，禁止持有 Request 对象）。"""
        try:
            # 判断操作是否成功
            success = 200 <= response_status < 400

            # 获取操作类型和描述
            action_type = self._get_action_type(snapshot.path)
            action = self._get_action_description(snapshot.method, snapshot.path)

            # 构建详细信息
            # query_params 在 snapshot 内用 tuple 存储（让 snapshot 可哈希），
            # 但落库时先脱敏再转 dict，避免 PASSWORD=xxx / TOKEN=xxx 原样写入
            # operation_logs 集合（与 app.utils.secret_masking 保持一致规则）
            masked_params = mask_query_params(snapshot.query_params)
            details = {
                "method": snapshot.method,
                "path": snapshot.path,
                "status_code": response_status,
                "query_params": dict(masked_params) if masked_params else None,
            }

            # 获取错误信息（如果有）
            error_message = None
            if not success:
                error_message = f"HTTP {response_status}"

            # 记录操作日志
            await log_operation(
                user_id=user_info.get("id", ""),
                username=user_info.get("username", "unknown"),
                action_type=action_type,
                action=action,
                details=details,
                success=success,
                error_message=error_message,
                duration_ms=duration_ms,
                ip_address=ip_address,
                user_agent=user_agent,
                session_id=user_info.get("session_id")
            )

        except Exception as e:
            logger.error(f"记录操作日志失败: {e}")


# 便捷函数：手动记录操作日志
async def manual_log_operation(
    request: Request,
    user_info: Dict[str, Any],
    action_type: str,
    action: str,
    details: Optional[Dict[str, Any]] = None,
    success: bool = True,
    error_message: Optional[str] = None,
    duration_ms: Optional[int] = None
):
    """手动记录操作日志"""
    try:
        ip_address = _get_client_ip_from_request(request)
        user_agent = request.headers.get("user-agent", "")

        await log_operation(
            user_id=user_info.get("id", ""),
            username=user_info.get("username", "unknown"),
            action_type=action_type,
            action=action,
            details=details,
            success=success,
            error_message=error_message,
            duration_ms=duration_ms,
            ip_address=ip_address,
            user_agent=user_agent,
            session_id=user_info.get("session_id")
        )
    except Exception as e:
        logger.error(f"手动记录操作日志失败: {e}")
