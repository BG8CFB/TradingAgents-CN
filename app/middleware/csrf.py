"""CSRF 双提交 Cookie 中间件。

工作模式（适合前后端分离架构）：

1. **登录成功**（auth_db.py:login）：
   - 从 access_token 提取 jti（uuid4 不可推测）
   - 生成 csrf_token = hmac.new(CSRF_SECRET, jti, sha256).hexdigest()
   - Set-Cookie: csrf_token=<value>; HttpOnly=false; SameSite=Lax; Secure=<prod>
   - 同时在响应 body 中返回 csrf_token（前端读取后写入后续请求 Header）

2. **后续 state-changing 请求**（POST/PUT/PATCH/DELETE）：
   - 前端读 cookie + 加 Header: X-CSRF-Token: <value>
   - 中间件校验 cookie 值 == header 值（双提交）
   - 任一缺失或不一致 → 403 Forbidden

3. **Safe methods**（GET/HEAD/OPTIONS/TRACE）跳过校验

4. **WebSocket/SSE** 走独立 token 校验（在 routers 层处理），跳过此中间件

5. **注册顺序**：CSRFMiddleware 在 OperationLogMiddleware 之前
   （CSRF 失败的请求不应被记录为业务操作）

安全契约：
    - ``session_id`` 必须是不可被外部推断的随机值（如 JWT jti/uuid4）；
    - 切勿使用 username/email 等公开信息作为 ``session_id``，否则攻击者可自行计算合法 token。

设计参考：OWASP CSRF Prevention Cheat Sheet — Double Submit Cookie 模式。
"""

import hmac
import hashlib
import logging

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.config import settings

logger = logging.getLogger("webapi")

# safe methods per RFC 7231
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "TRACE"})

CSRF_COOKIE_NAME = "csrf_token"
CSRF_HEADER_NAME = "X-CSRF-Token"

# 豁免路径：登录/注册/刷新是 CSRF token 的初始获取来源，本身不依赖前置 CSRF
# 提到模块级常量，避免每次请求都重建 frozenset
EXEMPT_PATHS = frozenset({
    "/api/auth/login",
    "/api/auth/register",
    "/api/auth/refresh",
    "/api/auth/csrf-token",  # 显式获取 CSRF token 的端点
    "/api/health",
    "/api/health/live",
    "/api/health/ready",
})


def generate_csrf_token(session_id: str) -> str:
    """基于 session_id 和 CSRF_SECRET 生成 HMAC-SHA256 token。

    Args:
        session_id: JWT jti（uuid4 不可推测）或随机会话 ID。
            **严禁使用 username/email 等公开信息**。

    Returns:
        64 位十六进制字符串
    """
    secret = settings.CSRF_SECRET.encode("utf-8")
    msg = session_id.encode("utf-8")
    return hmac.new(secret, msg, hashlib.sha256).hexdigest()


def set_csrf_cookie(response: Response, token: str) -> None:
    """在响应中设置 CSRF Cookie。

    - 生产（DEBUG=False）：Secure=True
    - 开发：Secure=False（允许 HTTP localhost）
    """
    secure = not settings.DEBUG
    response.set_cookie(
        key=CSRF_COOKIE_NAME,
        value=token,
        max_age=7 * 24 * 3600,  # 7 天
        httponly=False,  # 前端 JS 需读取
        samesite="lax",
        secure=secure,
        path="/",
    )


class CSRFMiddleware(BaseHTTPMiddleware):
    """CSRF 双提交 Cookie 校验中间件。"""

    async def dispatch(self, request: Request, call_next):
        # safe methods 跳过校验
        if request.method in SAFE_METHODS:
            return await call_next(request)

        # WebSocket / SSE 升级请求跳过（由独立 token 校验）
        if request.url.path.startswith("/ws") or request.url.path.startswith("/api/sse"):
            return await call_next(request)

        # 登录/注册端点豁免（这些是 CSRF token 的初始获取来源）
        if request.url.path in EXEMPT_PATHS:
            return await call_next(request)

        # 双提交校验：cookie 与 header 必须一致
        cookie_token = request.cookies.get(CSRF_COOKIE_NAME)
        header_token = request.headers.get(CSRF_HEADER_NAME)

        if not cookie_token or not header_token:
            logger.warning(
                f"CSRF 校验失败：缺失 token "
                f"(cookie={'有' if cookie_token else '无'}, "
                f"header={'有' if header_token else '无'}) "
                f"path={request.url.path}"
            )
            return JSONResponse(
                status_code=403,
                content={"detail": "CSRF token 缺失"},
            )

        if not hmac.compare_digest(cookie_token, header_token):
            logger.warning(f"CSRF 校验失败：token 不一致 path={request.url.path}")
            return JSONResponse(
                status_code=403,
                content={"detail": "CSRF token 无效"},
            )

        return await call_next(request)
