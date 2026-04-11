import time
from datetime import timedelta
from app.utils.timezone import now_tz
from typing import Optional
import jwt
import logging
from pydantic import BaseModel
from app.core.config import settings

class TokenData(BaseModel):
    sub: str
    exp: int

class AuthService:
    @staticmethod
    def create_access_token(sub: str, expires_minutes: int | None = None, expires_delta: int | None = None) -> str:
        if expires_delta:
            # 如果指定了秒数，使用秒数
            expire = now_tz() + timedelta(seconds=expires_delta)
        else:
            # 否则使用分钟数
            expire = now_tz() + timedelta(minutes=expires_minutes or settings.ACCESS_TOKEN_EXPIRE_MINUTES)
        payload = {"sub": sub, "exp": expire}
        token = jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)
        return token

    @staticmethod
    def verify_token(token: str) -> Optional[TokenData]:
        logger = logging.getLogger(__name__)

        try:
            payload = jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])

            token_data = TokenData(sub=payload.get("sub"), exp=int(payload.get("exp", time.time())))

            # 检查是否过期
            current_time = int(time.time())
            if token_data.exp < current_time:
                logger.warning("⏰ Token已过期")
                return None

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
