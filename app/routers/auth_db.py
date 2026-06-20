"""
基于数据库的认证路由 - 改进版
替代原有的基于配置文件的认证机制
"""

import time
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Header, Request
from pydantic import BaseModel

from app.services.auth_service import AuthService
from app.services.user_service import user_service
from app.core.config import settings
from app.core.response import safe_error_message
from app.models.user import UserCreate
from app.services.operation_log_service import log_operation
from app.models.operation_log import ActionType
from app.utils.secret_masking import mask_username, token_fingerprint

# 尝试导入日志管理器
try:
    from app.utils.logging_manager import get_logger
except ImportError:
    # 如果导入失败，使用标准日志
    import logging
    def get_logger(name: str) -> logging.Logger:
        return logging.getLogger(name)

logger = get_logger('auth_db')


def validate_password_strength(password: str) -> None:
    """验证密码强度，不符合则抛出 HTTPException。"""
    if len(password) < 8:
        raise HTTPException(status_code=400, detail="密码长度不能少于8位")
    has_letter = any(c.isalpha() for c in password)
    has_digit = any(c.isdigit() for c in password)
    if not (has_letter and has_digit):
        raise HTTPException(status_code=400, detail="密码必须同时包含字母和数字")


# 统一响应格式
class ApiResponse(BaseModel):
    success: bool = True
    data: dict = {}
    message: str = ""

class UserUpdateRequest(BaseModel):
    """用户信息更新请求模型 - 仅允许修改的字段"""
    email: Optional[str] = None
    preferences: Optional[dict] = None
    language: Optional[str] = None

router = APIRouter(prefix="/api/auth", tags=["Auth"])

# refresh_token 生命周期常量：集中管理避免散落在多处出现魔法数字
_REFRESH_TOKEN_TTL_SECONDS = 60 * 60 * 24 * 7  # 7 天，单位：秒
_REFRESH_TOKEN_TTL_DAYS = 7  # 7 天，单位：天（黑名单 TTL 用）

# access_token 黑名单 TTL：与 settings.ACCESS_TOKEN_EXPIRE_MINUTES 对齐。
# logout 时把 access_token 加黑名单，使其在剩余有效期内立即失效；
# TTL 取过期分钟数 +1 分钟缓冲，避免 token 刚好过期时黑名单已提前清除
# （清除也无害，因为 token 本身已过期，verify_token 会拒绝）。
_ACCESS_TOKEN_BLACKLIST_TTL_SECONDS = (settings.ACCESS_TOKEN_EXPIRE_MINUTES + 1) * 60


class LoginRequest(BaseModel):
    username: str
    password: str

class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: dict

class RefreshTokenRequest(BaseModel):
    refresh_token: str

class RefreshTokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int

class ChangePasswordRequest(BaseModel):
    old_password: str
    new_password: str

class ResetPasswordRequest(BaseModel):
    username: str
    new_password: str

class CreateUserRequest(BaseModel):
    username: str
    email: str
    password: str
    is_admin: bool = False


async def _add_token_to_blacklist(
    token: str, ttl_days: int = 7, *, ttl_seconds: Optional[int] = None
) -> bool:
    """把 token 写入 Redis 黑名单（用于 logout / refresh_token 轮换）。

    黑名单 key 形如 ``token_blacklist:{sha256_hash}``，TTL 与 token 剩余有效期对齐。

    TTL 指定方式（二选一，``ttl_seconds`` 优先）：
        - ``ttl_seconds``：直接指定秒数。用于 access_token（TTL=60分钟+缓冲），
          避免把"分钟级"token 写入"天级"黑名单造成 Redis 无谓堆积。
        - ``ttl_days``：便捷参数，内部换算为秒。用于 refresh_token（TTL=7天）。

    Args:
        token: 要拉黑的 token 原文
        ttl_days: 黑名单保留天数（当 ``ttl_seconds`` 未指定时使用）
        ttl_seconds: 黑名单保留秒数（优先于 ``ttl_days``）

    Returns:
        True 表示写入成功；False 表示 Redis 不可用（业务流程允许继续，验证时再判断）
    """
    if not token:
        return False
    import hashlib
    effective_ttl = ttl_seconds if ttl_seconds is not None else ttl_days * 24 * 3600
    try:
        from app.data.storage.redis.client import get_redis
        redis = get_redis()
        if not redis:
            return False
        token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
        await redis.set(
            f"token_blacklist:{token_hash}",
            "1",
            ex=effective_ttl,
        )
        return True
    except Exception as exc:
        logger.debug(f"token 黑名单写入失败: {exc}")
        return False


async def _is_token_blacklisted(token: str, *, fail_closed: bool = False) -> bool:
    """检查 token 是否在黑名单中。

    Args:
        token: 待检查的 JWT
        fail_closed: True 时 Redis 异常即视为"已撤销"（refresh 路径用）；
                     False 时返回 False（登录路径用，避免 Redis 抖动锁死用户）。
    """
    if not token:
        return False
    import hashlib
    try:
        from app.data.storage.redis.client import get_redis
        redis = get_redis()
        if not redis:
            if fail_closed:
                logger.warning("Redis 不可用且 fail_closed=True，拒绝 refresh token")
                return True
            return False
        token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
        return bool(await redis.get(f"token_blacklist:{token_hash}"))
    except Exception as exc:
        logger.debug(f"token 黑名单检查失败: {exc}")
        if fail_closed:
            logger.warning(f"token 黑名单检查异常 fail_closed=True，拒绝 token: {exc}")
            return True
        return False


async def get_current_user(authorization: Optional[str] = Header(default=None)) -> dict:
    """获取当前用户信息"""
    logger.debug("🔐 认证检查开始")
    logger.debug(f"📋 Authorization header: {'present' if authorization else 'missing'}, len={len(authorization) if authorization else 0}")

    if not authorization:
        logger.warning("❌ 没有Authorization header")
        raise HTTPException(status_code=401, detail="No authorization header")

    if not authorization.lower().startswith("bearer "):
        logger.warning("❌ Authorization header格式错误: 前缀不符合 Bearer 格式")
        raise HTTPException(status_code=401, detail="Invalid authorization format")

    token = authorization.split(" ", 1)[1]
    logger.debug(f"🎫 提取的token长度: {len(token)}")
    logger.debug(f"🎫 Token指纹: {token_fingerprint(token)}")

    token_data = AuthService.verify_token(token)
    logger.debug(f"🔍 Token验证结果: {token_data is not None}")

    if not token_data:
        logger.warning("❌ Token验证失败")
        raise HTTPException(status_code=401, detail="Invalid token")

    # Token 黑名单检查（logout 后旧 access_token 应立即失效）
    # fail_closed=False：Redis 故障时放行，避免单点故障锁死所有用户；
    # 这与原 fail-closed 限流策略不同，因为认证路径直接影响业务可用性
    if await _is_token_blacklisted(token, fail_closed=False):
        logger.warning(
            f"❌ Token 已被吊销: fp={token_fingerprint(token)}, user={mask_username(token_data.sub)}"
        )
        raise HTTPException(status_code=401, detail="Token has been revoked")

    # 从数据库获取用户信息
    user = await user_service.get_user_by_username(token_data.sub)
    if not user:
        logger.warning(f"❌ 用户不存在: {mask_username(token_data.sub)}")
        raise HTTPException(status_code=401, detail="User not found")

    if not user.is_active:
        logger.warning(f"❌ 用户已禁用: {mask_username(token_data.sub)}")
        raise HTTPException(status_code=401, detail="User is inactive")

    logger.debug(f"✅ 认证成功，用户: {mask_username(token_data.sub)}")

    # 返回完整的用户信息，包括偏好设置
    return {
        "id": str(user.id),
        "username": user.username,
        "email": user.email,
        "name": user.username,
        "is_admin": user.is_admin,
        "roles": ["admin"] if user.is_admin else ["user"],
        "preferences": user.preferences.model_dump() if user.preferences else {}
    }


async def require_admin(current_user: dict = Depends(get_current_user)) -> dict:
    """要求管理员权限的依赖"""
    if not current_user.get("is_admin", False):
        raise HTTPException(status_code=403, detail="需要管理员权限")
    return current_user

@router.post("/login")
async def login(payload: LoginRequest, request: Request):
    """用户登录"""
    start_time = time.time()

    # 获取客户端信息（考虑反向代理）
    from app.middleware.operation_log_middleware import _get_client_ip_from_request
    ip_address = _get_client_ip_from_request(request)
    user_agent = request.headers.get("user-agent", "")

    logger.info(f"🔐 登录请求 - 用户名: {mask_username(payload.username)}, IP: {ip_address}")

    try:
        # 验证输入
        if not payload.username or not payload.password:
            logger.warning("❌ 登录失败 - 用户名或密码为空")
            await log_operation(
                user_id="unknown",
                username=payload.username or "unknown",
                action_type=ActionType.USER_LOGIN,
                action="用户登录",
                details={"reason": "用户名和密码不能为空"},
                success=False,
                error_message="用户名和密码不能为空",
                duration_ms=int((time.time() - start_time) * 1000),
                ip_address=ip_address,
                user_agent=user_agent
            )
            raise HTTPException(status_code=400, detail="用户名和密码不能为空")

        # 防爆破：检查是否已被锁定（基于 IP + 用户名双维度）
        from app.core.auth_rate_limiter import get_auth_rate_limiter
        limiter = get_auth_rate_limiter()
        is_locked, lock_reason, retry_after = await limiter.check(ip_address, payload.username)
        if is_locked:
            logger.warning(
                f"🚨 登录被拒（已锁定）- 用户: {mask_username(payload.username)}, "
                f"IP: {ip_address}, 原因: {lock_reason}, 剩余: {retry_after}s"
            )
            await log_operation(
                user_id="unknown",
                username=payload.username,
                action_type=ActionType.USER_LOGIN,
                action="用户登录",
                details={"reason": lock_reason, "retry_after": retry_after},
                success=False,
                error_message=lock_reason,
                duration_ms=int((time.time() - start_time) * 1000),
                ip_address=ip_address,
                user_agent=user_agent
            )
            raise HTTPException(
                status_code=429,
                detail=f"{lock_reason}，请 {retry_after} 秒后重试" if retry_after else lock_reason,
                headers={"Retry-After": str(retry_after)} if retry_after else None,
            )

        logger.info(f"🔍 开始认证用户: {mask_username(payload.username)}")

        # 使用数据库认证
        user = await user_service.authenticate_user(payload.username, payload.password)

        logger.info(f"🔍 认证结果: user={'存在' if user else '不存在'}")

        if not user:
            logger.warning(f"❌ 登录失败 - 用户名或密码错误: {mask_username(payload.username)}")

            # 防爆破：记录失败，若触发阈值则锁定
            now_locked, lock_reason, lock_seconds = await limiter.record_failure(
                ip_address, payload.username
            )
            error_detail = "用户名或密码错误"
            if now_locked:
                error_detail = f"{lock_reason}，请 {lock_seconds // 60} 分钟后重试"

            await log_operation(
                user_id="unknown",
                username=payload.username,
                action_type=ActionType.USER_LOGIN,
                action="用户登录",
                details={"reason": "用户名或密码错误", "locked": now_locked},
                success=False,
                error_message=error_detail,
                duration_ms=int((time.time() - start_time) * 1000),
                ip_address=ip_address,
                user_agent=user_agent
            )
            status_code = 429 if now_locked else 401
            raise HTTPException(
                status_code=status_code,
                detail=error_detail,
                headers={"Retry-After": str(lock_seconds)} if now_locked else None,
            )

        # 防爆破：认证成功，清除该 IP + 用户名的失败计数
        await limiter.reset(ip_address, payload.username)

        # 生成 token
        token = AuthService.create_access_token(sub=user.username)
        refresh_token = AuthService.create_access_token(sub=user.username, expires_delta=_REFRESH_TOKEN_TTL_SECONDS, token_type="refresh")

        # 生成 CSRF token：基于 access_token 的 jti（uuid4 不可推测），而非 username
        # 安全原则：CSRF token 必须不可被外部推断；username 是公开信息，不可单独作为 HMAC 输入
        access_jti = AuthService.extract_jti(token) or f"fallback:{user.username}:{int(time.time())}"
        from app.middleware.csrf import generate_csrf_token, set_csrf_cookie
        from fastapi.responses import JSONResponse as _JSONResponse
        csrf_token = generate_csrf_token(access_jti)

        # 记录登录成功日志
        await log_operation(
            user_id=str(user.id),
            username=user.username,
            action_type=ActionType.USER_LOGIN,
            action="用户登录",
            details={"login_method": "password"},
            success=True,
            duration_ms=int((time.time() - start_time) * 1000),
            ip_address=ip_address,
            user_agent=user_agent
        )

        # 直接对最终的 JSONResponse 调用 set_csrf_cookie
        # （避免临时 Response + 手动拷贝 set-cookie header 的反模式，
        #  那种写法在多次 set_cookie 或中间件链路复杂时会互相覆盖）
        body = {
            "success": True,
            "data": {
                "access_token": token,
                "refresh_token": refresh_token,
                "expires_in": 60 * 60,
                "csrf_token": csrf_token,
                "user": {
                    "id": str(user.id),
                    "username": user.username,
                    "email": user.email,
                    "name": user.username,
                    "is_admin": user.is_admin,
                    "roles": ["admin"] if user.is_admin else ["user"],
                    "must_change_password": getattr(user, "must_change_password", False),
                }
            },
            "message": "登录成功"
        }
        json_resp = _JSONResponse(content=body)
        set_csrf_cookie(json_resp, csrf_token)
        return json_resp
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ 登录异常: {e}")
        await log_operation(
            user_id="unknown",
            username=payload.username or "unknown",
            action_type=ActionType.USER_LOGIN,
            action="用户登录",
            details={"error": str(e)},
            success=False,
            error_message=f"系统错误: {str(e)}",
            duration_ms=int((time.time() - start_time) * 1000),
            ip_address=ip_address,
            user_agent=user_agent
        )
        raise HTTPException(status_code=500, detail="登录过程中发生系统错误")

@router.post("/refresh")
async def refresh_token(payload: RefreshTokenRequest):
    """刷新访问令牌。

    安全要点：
    - 旧 refresh_token 必须先检查黑名单，已撤销的 token 不能再次使用
    - 颁发新 token 后立即把旧 refresh_token 写入黑名单（轮换），防止重放攻击
    - 轮换时一并签发新的 CSRF token（与 access_token 同生命周期），保证前端
      收到响应后立即更新 X-CSRF-Token，避免旧 CSRF Cookie 跨 refresh 后失效
    """
    try:
        logger.debug("🔄 收到refresh token请求")
        logger.debug(f"📝 Refresh token指纹: {token_fingerprint(payload.refresh_token)}")

        if not payload.refresh_token:
            logger.warning("❌ Refresh token为空")
            raise HTTPException(status_code=401, detail="Refresh token is required")

        # 检查 token 是否在黑名单中（已被登出或已轮换使用）
        # refresh 路径必须 fail_closed：Redis 异常时拒绝 token，避免被撤销的 token 重新生效
        if await _is_token_blacklisted(payload.refresh_token, fail_closed=True):
            logger.warning(f"❌ Refresh token已被撤销，指纹={token_fingerprint(payload.refresh_token)}")
            raise HTTPException(status_code=401, detail="Token has been revoked")

        # 验证refresh token
        token_data = AuthService.verify_token(payload.refresh_token)
        logger.debug(f"🔍 Token验证结果: {token_data is not None}")

        if not token_data:
            logger.warning("❌ Refresh token验证失败")
            raise HTTPException(status_code=401, detail="Invalid refresh token")

        if getattr(token_data, 'type', 'access') != 'refresh':
            logger.warning("❌ 非 refresh token 类型，拒绝刷新")
            raise HTTPException(status_code=401, detail="Not a refresh token")

        # 验证用户是否仍然存在且激活
        user = await user_service.get_user_by_username(token_data.sub)
        if not user or not user.is_active:
            logger.warning(f"❌ 用户不存在或已禁用: {mask_username(token_data.sub)}")
            raise HTTPException(status_code=401, detail="User not found or inactive")

        logger.debug(f"✅ Token验证成功，用户: {mask_username(token_data.sub)}")

        # 生成新的tokens
        new_token = AuthService.create_access_token(sub=token_data.sub)
        new_refresh_token = AuthService.create_access_token(sub=token_data.sub, expires_delta=_REFRESH_TOKEN_TTL_SECONDS, token_type="refresh")

        # 关键：把旧 refresh_token 加入黑名单（轮换），TTL 与 refresh_token 有效期一致
        # 这样即使旧 token 泄漏，攻击者也无法再次使用它刷新出新 access_token
        await _add_token_to_blacklist(payload.refresh_token, ttl_days=_REFRESH_TOKEN_TTL_DAYS)

        # 同时轮换 CSRF token：基于新 access_token 的 jti（uuid4 不可推测）
        # 前端 refresh 完成后用新 csrf_token 更新 Cookie + Header，避免旧 token 滞留
        new_access_jti = AuthService.extract_jti(new_token) or f"fallback:{user.username}:{int(time.time())}"
        from app.middleware.csrf import generate_csrf_token, set_csrf_cookie
        from fastapi.responses import JSONResponse as _JSONResponse
        new_csrf_token = generate_csrf_token(new_access_jti)
        body = {
            "success": True,
            "data": {
                "access_token": new_token,
                "refresh_token": new_refresh_token,
                "expires_in": 60 * 60,
                "csrf_token": new_csrf_token,
            },
            "message": "Token刷新成功"
        }
        json_resp = _JSONResponse(content=body)
        set_csrf_cookie(json_resp, new_csrf_token)

        logger.debug("🎉 新token生成成功，旧 refresh_token 已加入黑名单")

        return json_resp
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Refresh token处理异常: {str(e)}")
        raise HTTPException(status_code=401, detail=safe_error_message(e, "Token刷新失败"))

class LogoutRequest(BaseModel):
    refresh_token: Optional[str] = None


@router.post("/logout")
async def logout(request: Request, user: dict = Depends(get_current_user)):
    """用户登出"""
    start_time = time.time()

    # 获取客户端信息（考虑反向代理）
    from app.middleware.operation_log_middleware import _get_client_ip_from_request
    ip_address = _get_client_ip_from_request(request)
    user_agent = request.headers.get("user-agent", "")

    try:
        # 从 Authorization header 提取 access_token 并加入黑名单（即时失效）。
        # 这与 get_current_user 中的 access_token 黑名单检查配套：
        # logout 前该检查永远不会命中（黑名单为空），logout 后立即命中。
        # TTL 与 access_token 剩余有效期对齐，过期后黑名单条目自动清除。
        authorization = request.headers.get("authorization", "")
        if authorization.lower().startswith("bearer "):
            access_token = authorization.split(" ", 1)[1]
            await _add_token_to_blacklist(
                access_token, ttl_seconds=_ACCESS_TOKEN_BLACKLIST_TTL_SECONDS
            )

        # 尝试解析请求体中的 refresh_token 并加入黑名单
        try:
            body = await request.json()
            refresh_token = body.get("refresh_token") if body else None
            if refresh_token:
                await _add_token_to_blacklist(refresh_token, ttl_days=_REFRESH_TOKEN_TTL_DAYS)
        except Exception as e:
            logger.debug(f"登出 token 处理失败: {e}")
            pass

        # 记录登出日志
        await log_operation(
            user_id=user["id"],
            username=user["username"],
            action_type=ActionType.USER_LOGOUT,
            action="用户登出",
            details={"logout_method": "manual"},
            success=True,
            duration_ms=int((time.time() - start_time) * 1000),
            ip_address=ip_address,
            user_agent=user_agent
        )

        return {
            "success": True,
            "data": {},
            "message": "登出成功"
        }
    except Exception as e:
        logger.error(f"记录登出日志失败: {e}")
        return {
            "success": True,
            "data": {},
            "message": "登出成功"
        }

@router.get("/me")
async def me(user: dict = Depends(get_current_user)):
    """获取当前用户信息"""
    return {
        "success": True,
        "data": user,
        "message": "获取用户信息成功"
    }

@router.get("/csrf-token")
async def get_csrf_token(request: Request, user: dict = Depends(get_current_user)):
    """获取当前用户的 CSRF token（OWASP 推荐的"显式获取端点"模式兜底）。

    使用场景：
        1. 前端启动时发现本地无 csrf_token Cookie（或 Cookie 已过期），
           通过此端点拉取新 token 并 Set-Cookie；
        2. 双提交 Cookie 模式下，前端从 cookie 读不到值时的修复路径；
        3. 浏览器禁用第三方 Cookie 或 Samesite=Lax 跨子域共享场景下，
           显式通过 API 拿值，确保不依赖登录页注入。

    本端点依赖 ``get_current_user``，所以必须携带有效 access_token。
    返回值中同时下发 body.csrf_token 与 Set-Cookie，前端只需更新本地状态即可。

    CSRF token 派生自请求 JWT 的 jti（uuid4 不可推测），与 access_token 同生命周期。
    """
    from app.middleware.csrf import generate_csrf_token, set_csrf_cookie
    from fastapi.responses import JSONResponse as _JSONResponse

    # 从请求 Authorization header 解析 jti；失败时回退到 user+timestamp 保证唯一性
    authorization = request.headers.get("authorization", "")
    session_id = f"fallback:{user['username']}:{int(time.time())}"
    if authorization.lower().startswith("bearer "):
        jwt_token = authorization.split(" ", 1)[1]
        jti = AuthService.extract_jti(jwt_token)
        if jti:
            session_id = jti

    csrf_token = generate_csrf_token(session_id)
    body = {
        "success": True,
        "data": {"csrf_token": csrf_token},
        "message": "CSRF token 获取成功",
    }
    resp = _JSONResponse(content=body)
    set_csrf_cookie(resp, csrf_token)
    return resp

@router.put("/me")
async def update_me(
    payload: UserUpdateRequest,
    user: dict = Depends(get_current_user)
):
    """更新当前用户信息"""
    try:
        from app.models.user import UserUpdate, UserPreferences

        # 构建更新数据
        update_data = {}

        # 更新邮箱
        if payload.email is not None:
            update_data["email"] = payload.email

        # 更新偏好设置（支持部分更新）
        if payload.preferences is not None:
            # 获取当前偏好
            current_prefs = user.get("preferences", {})

            # 合并新的偏好设置
            merged_prefs = {**current_prefs, **payload.preferences}

            # 创建 UserPreferences 对象
            update_data["preferences"] = UserPreferences(**merged_prefs)

        # 如果有语言设置，更新到偏好中
        if payload.language is not None:
            if "preferences" not in update_data:
                # 获取当前偏好
                current_prefs = user.get("preferences", {})
                update_data["preferences"] = UserPreferences(**current_prefs)
            update_data["preferences"].language = payload.language

        # 如果没有可更新的字段，直接返回
        if not update_data:
            raise HTTPException(status_code=400, detail="没有可更新的字段")

        # 调用服务更新用户
        user_update = UserUpdate(**update_data)
        updated_user = await user_service.update_user(user["username"], user_update)

        if not updated_user:
            raise HTTPException(status_code=400, detail="更新失败，邮箱可能已被使用")

        # 返回更新后的用户信息（排除敏感字段）
        return {
            "success": True,
            "data": updated_user.model_dump(by_alias=True, exclude={"hashed_password"}),
            "message": "用户信息更新成功"
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"更新用户信息失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=safe_error_message(e, "更新用户信息失败"))

@router.post("/change-password")
async def change_password(
    payload: ChangePasswordRequest,
    request: Request,
    user: dict = Depends(get_current_user)
):
    """修改密码"""
    try:
        # 新密码强度验证
        validate_password_strength(payload.new_password)

        # 使用数据库服务修改密码
        success = await user_service.change_password(
            user["username"], 
            payload.old_password, 
            payload.new_password
        )
        
        if not success:
            raise HTTPException(status_code=400, detail="旧密码错误")

        return {
            "success": True,
            "data": {},
            "message": "密码修改成功"
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"修改密码失败: {e}")
        raise HTTPException(status_code=500, detail=safe_error_message(e, "修改密码失败"))

@router.post("/reset-password")
async def reset_password(
    payload: ResetPasswordRequest,
    request: Request,
    user: dict = Depends(get_current_user)
):
    """重置密码（管理员操作）"""
    try:
        # 检查权限
        if not user.get("is_admin", False):
            raise HTTPException(status_code=403, detail="权限不足")

        # 密码强度验证
        validate_password_strength(payload.new_password)

        # 重置密码
        success = await user_service.reset_password(payload.username, payload.new_password)
        
        if not success:
            raise HTTPException(status_code=404, detail="用户不存在")

        return {
            "success": True,
            "data": {},
            "message": f"用户 {payload.username} 的密码已重置"
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"重置密码失败: {e}")
        raise HTTPException(status_code=500, detail=safe_error_message(e, "重置密码失败"))

class RegisterRequest(BaseModel):
    username: str
    email: str
    password: str

@router.post("/register")
async def register(payload: RegisterRequest, request: Request):
    """用户公开注册（无需认证）"""
    # 注册开关检查：非 DEBUG（生产）环境下需要管理员显式开放注册
    if not settings.DEBUG:
        from app.core.env import get_env
        if get_env("REGISTRATION_ENABLED", "").lower() not in ("true", "1", "yes"):
            raise HTTPException(status_code=403, detail="当前未开放注册，请联系管理员")

    start_time = time.time()
    # 获取客户端信息（考虑反向代理）
    from app.middleware.operation_log_middleware import _get_client_ip_from_request
    ip_address = _get_client_ip_from_request(request)

    logger.info(f"📝 注册请求 - 用户名: {payload.username}, IP: {ip_address}")

    try:
        if not payload.username or not payload.email or not payload.password:
            raise HTTPException(status_code=400, detail="用户名、邮箱和密码不能为空")

        validate_password_strength(payload.password)

        user_create = UserCreate(
            username=payload.username,
            email=payload.email,
            password=payload.password
        )

        new_user = await user_service.create_user(user_create)

        if not new_user:
            raise HTTPException(status_code=400, detail="用户名或邮箱已存在")

        # 自动生成 token，注册后直接登录
        token = AuthService.create_access_token(sub=new_user.username)
        refresh_token = AuthService.create_access_token(sub=new_user.username, expires_delta=_REFRESH_TOKEN_TTL_SECONDS, token_type="refresh")

        await log_operation(
            user_id=str(new_user.id),
            username=new_user.username,
            action_type=ActionType.USER_LOGIN,
            action="用户注册",
            details={"method": "register"},
            success=True,
            duration_ms=int((time.time() - start_time) * 1000),
            ip_address=ip_address,
            user_agent=request.headers.get("user-agent", "")
        )

        # 注册即登录：同步签发 CSRF token（基于 access_token jti，与 login 路径一致）
        # 注册端点在 CSRF 中间件 exempt_paths 中，可以无 token 调用；返回时必须下发新 Cookie
        access_jti = AuthService.extract_jti(token) or f"fallback:{new_user.username}:{int(time.time())}"
        from app.middleware.csrf import generate_csrf_token, set_csrf_cookie
        from fastapi.responses import JSONResponse as _JSONResponse
        csrf_token = generate_csrf_token(access_jti)
        body = {
            "success": True,
            "data": {
                "access_token": token,
                "refresh_token": refresh_token,
                "expires_in": 60 * 60,
                "csrf_token": csrf_token,
                "user": {
                    "id": str(new_user.id),
                    "username": new_user.username,
                    "email": new_user.email,
                    "name": new_user.username,
                    "is_admin": False,
                    "roles": ["user"],
                }
            },
            "message": "注册成功"
        }
        json_resp = _JSONResponse(content=body)
        set_csrf_cookie(json_resp, csrf_token)
        return json_resp
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ 注册异常: {e}")
        raise HTTPException(status_code=500, detail="注册过程中发生系统错误")


@router.post("/create-user")
async def create_user(
    payload: CreateUserRequest,
    request: Request,
    user: dict = Depends(get_current_user)
):
    """创建用户（管理员操作）"""
    try:
        # 检查权限
        if not user.get("is_admin", False):
            raise HTTPException(status_code=403, detail="权限不足")

        # 密码强度验证
        validate_password_strength(payload.password)

        # 创建用户
        user_create = UserCreate(
            username=payload.username,
            email=payload.email,
            password=payload.password
        )
        
        new_user = await user_service.create_user(user_create)
        
        if not new_user:
            raise HTTPException(status_code=400, detail="用户名或邮箱已存在")

        # 如果需要设置为管理员，复用现有异步用户服务，避免额外同步连接泄漏
        if payload.is_admin:
            admin_updated = await user_service.set_admin_status(payload.username, True)
            if not admin_updated:
                raise HTTPException(status_code=500, detail="用户已创建，但管理员权限设置失败")

        return {
            "success": True,
            "data": {
                "id": str(new_user.id),
                "username": new_user.username,
                "email": new_user.email,
                "is_admin": payload.is_admin
            },
            "message": f"用户 {payload.username} 创建成功"
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"创建用户失败: {e}")
        raise HTTPException(status_code=500, detail=safe_error_message(e, "创建用户失败"))

@router.get("/users")
async def list_users(
    skip: int = 0,
    limit: int = 100,
    user: dict = Depends(get_current_user)
):
    """获取用户列表（管理员操作）"""
    try:
        # 检查权限
        if not user.get("is_admin", False):
            raise HTTPException(status_code=403, detail="权限不足")

        users = await user_service.list_users(skip=skip, limit=limit)

        return {
            "success": True,
            "data": {
                # 安全：序列化用户对象时显式排除 hashed_password，避免凭证泄漏
                "users": [user.model_dump(exclude={"hashed_password"}) for user in users],
                "total": len(users)
            },
            "message": "获取用户列表成功"
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取用户列表失败: {e}")
        raise HTTPException(status_code=500, detail=safe_error_message(e, "获取用户列表失败"))
