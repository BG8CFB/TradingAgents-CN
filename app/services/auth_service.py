from datetime import datetime, timedelta, timezone
from typing import Optional
import jwt
import logging
import uuid
from pydantic import BaseModel
from app.core.config import settings

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
        logger = logging.getLogger(__name__)

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
