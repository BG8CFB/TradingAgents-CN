from datetime import datetime, timedelta, timezone
from typing import Optional
import hashlib
import jwt
import logging
import uuid
from pydantic import BaseModel
from app.core.config import settings

logger = logging.getLogger(__name__)


class TokenData(BaseModel):
    sub: str
    exp: int
    type: str = "access"


class AuthService:
    @staticmethod
    def create_access_token(sub: str, expires_minutes: int | None = None, expires_delta: int | None = None, token_type: str = "access") -> str:
        if expires_delta:
            # 如果指定了秒数，使用秒数
            now = datetime.now(timezone.utc)
            expire = now + timedelta(seconds=expires_delta)
        else:
            # 否则使用分钟数
            now = datetime.now(timezone.utc)
            expire = now + timedelta(minutes=expires_minutes or settings.ACCESS_TOKEN_EXPIRE_MINUTES)
        # iat + jti 保证每次生成的 token 字符串唯一：
        # 否则同一秒内为同一用户生成的两个 refresh_token 会完全相同，
        # 导致 refresh_token 轮换黑名单误把"新 token"也拉黑。
        payload = {
            "sub": sub,
            "exp": expire,
            "iat": now,
            "jti": uuid.uuid4().hex,
            "type": token_type,
        }
        token = jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)
        return token

    @staticmethod
    def verify_token(token: str) -> Optional[TokenData]:
        try:
            # jwt.decode 内部已自动处理过期检查，过期时抛出 ExpiredSignatureError
            payload = jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])

            token_data = TokenData(sub=payload.get("sub"), exp=int(payload.get("exp", 0)), type=payload.get("type", "access"))

            return token_data

        except jwt.ExpiredSignatureError:
            logger.warning("⏰ Token已过期")
            return None
        except jwt.InvalidTokenError as e:
            logger.warning(f"❌ Token无效: {str(e)}")
            return None
        except Exception as e:
            logger.error(f"❌ Token验证异常: {str(e)}")
            return None

    @staticmethod
    def extract_jti(token: str) -> Optional[str]:
        """从 JWT 中提取 jti（不动 exp 校验，仅解包 payload）。

        用于 CSRF token 派生：登录/刷新后从 access_token 提取 jti（uuid4），
        让 CSRF token 与本会话 access_token 严格 1:1 绑定，且不可被外部推断。
        任何失败都返回 None，由调用方走 fallback 路径。
        """
        if not token:
            return None
        try:
            # options={"verify_exp": False} 避免过期 token 也提取不出 jti
            # CSRF 端点依赖 get_current_user 已过滤过期 token，这里只是兜底解包
            payload = jwt.decode(
                token,
                settings.JWT_SECRET,
                algorithms=[settings.JWT_ALGORITHM],
                options={"verify_exp": False},
            )
            return payload.get("jti")
        except Exception:
            return None

    @staticmethod
    def _token_hash(token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    @staticmethod
    async def add_token_to_blacklist(
        token: str, ttl_seconds: int
    ) -> bool:
        """把 token 写入 Redis 黑名单（logout / refresh_token 轮换）。

        Returns:
            True 表示写入成功；False 表示 Redis 不可用或 token 为空。
        """
        if not token:
            return False
        try:
            from app.data.storage.redis.client import get_redis
            redis = get_redis()
            if not redis:
                return False
            await redis.set(
                f"token_blacklist:{AuthService._token_hash(token)}",
                "1",
                ex=ttl_seconds,
            )
            return True
        except Exception as exc:
            logger.debug(f"token 黑名单写入失败: {exc}")
            return False

    @staticmethod
    async def is_token_blacklisted(
        token: str, *, fail_closed: bool = False
    ) -> bool:
        """检查 token 是否在黑名单中。

        Args:
            token: 待检查的 JWT
            fail_closed: True 时 Redis 异常即视为"已撤销"（refresh 路径用）；
                         False 时返回 False（登录路径用，避免 Redis 抖动锁死用户）。
        """
        if not token:
            return False
        try:
            from app.data.storage.redis.client import get_redis
            redis = get_redis()
            if not redis:
                if fail_closed:
                    logger.warning(
                        "Redis 不可用且 fail_closed=True，拒绝 token"
                    )
                    return True
                return False
            return bool(
                await redis.get(
                    f"token_blacklist:{AuthService._token_hash(token)}"
                )
            )
        except Exception as exc:
            logger.debug(f"token 黑名单检查失败: {exc}")
            if fail_closed:
                logger.warning(
                    f"token 黑名单检查异常 fail_closed=True，拒绝 token: {exc}"
                )
                return True
            return False
