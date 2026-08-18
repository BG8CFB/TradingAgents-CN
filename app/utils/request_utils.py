"""请求工具函数。

提取中间件共享的请求处理逻辑，避免跨中间件模块的代码重复。
"""

import logging
from typing import Optional

from fastapi import Request

logger = logging.getLogger(__name__)


def get_client_ip(request: Request) -> str:
    """获取客户端真实 IP 地址（仅信任来自受信代理的代理头）。

    从 ``settings.TRUSTED_PROXIES`` 读取受信代理 IP 列表。仅当直连 IP
    来自受信代理时才解析 ``X-Forwarded-For`` / ``X-Real-IP`` 头。

    XFF 解析策略（RFC 7239 安全模式）：
    - 从 XFF 最右侧（紧邻受信代理的左侧）开始向左遍历；
    - 跳过所有在 TRUSTED_PROXIES 内的 IP；
    - 第一个不在白名单中的 IP 即真实客户端 IP。
    这防止了攻击者在 XFF 最左侧伪造 IP（旧实现取 ``split(",")[0]`` 的漏洞）。

    此函数由 ``RateLimitMiddleware`` 和 ``OperationLogMiddleware`` 共享使用。
    """
    direct_ip = request.client.host if request.client else "unknown"

    from app.core.config import settings
    trusted = set(p.strip() for p in settings.TRUSTED_PROXIES.split(",") if p.strip())
    if direct_ip in trusted:
        forwarded_for = request.headers.get("x-forwarded-for")
        if forwarded_for:
            # 从右向左遍历，跳过受信代理 IP，第一个非受信 IP 即真实客户端。
            # 若全部为受信代理（如多级反代），回退到最左侧（即最初的客户端自报 IP）。
            parts = [ip.strip() for ip in forwarded_for.split(",") if ip.strip()]
            for ip in reversed(parts):
                if ip not in trusted:
                    return ip
            return parts[0] if parts else direct_ip
        real_ip = request.headers.get("x-real-ip")
        if real_ip:
            return real_ip.strip()

    return direct_ip


def extract_user_id_from_jwt(request: Request) -> Optional[str]:
    """从 Authorization header 解析 JWT，返回用户标识（``sub`` 字段）。

    中间件在路由处理器之前执行，无法依赖 ``Depends(get_current_user)``
    写入的 ``request.state.user``。此函数提供与认证依赖一致的 JWT 解析逻辑，
    让限流/配额等中间件能基于真实 user_id 工作，而非全部退化为 IP 维度。

    与 ``OperationLogMiddleware._parse_jwt_user`` 使用相同的 decode 参数，
    但只返回 ``sub``（用户名/用户 ID），不提取 role / session_id 等额外字段。

    Args:
        request: FastAPI 请求对象

    Returns:
        JWT ``sub`` 字段值（通常为用户名）；无 Token / 解析失败 / 已过期
        时返回 ``None``。不抛出任何异常。
    """
    try:
        auth_header = request.headers.get("authorization", "")
        # RFC 6750 §2.1: Bearer scheme 不区分大小写
        parts = auth_header.split(" ", 1)
        if len(parts) != 2 or parts[0].lower() != "bearer":
            return None

        token = parts[1].strip()
        if not token:
            return None

        import jwt
        from app.core.config import settings

        payload = jwt.decode(
            token,
            settings.JWT_SECRET,
            algorithms=[settings.JWT_ALGORITHM],
            options={"verify_exp": True},
            leeway=5,
        )
        sub = payload.get("sub")
        return str(sub) if sub else None
    except Exception as e:
        logger.debug(f"extract_user_id_from_jwt 解析失败: {e}")
        return None
