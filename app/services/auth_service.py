from datetime import datetime, timedelta, timezone
from typing import Optional
import jwt
import logging
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
            expire = datetime.now(timezone.utc) + timedelta(seconds=expires_delta)
        else:
            # 否则使用分钟数
            expire = datetime.now(timezone.utc) + timedelta(minutes=expires_minutes or settings.ACCESS_TOKEN_EXPIRE_MINUTES)
        payload = {"sub": sub, "exp": expire, "type": token_type}
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
