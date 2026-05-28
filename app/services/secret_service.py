"""
安全密钥服务

管理 JWT_SECRET、CSRF_SECRET 等安全密钥的自动生成和持久化。
密钥存储在 MongoDB system_secrets 集合中，首次启动自动生成，
后续启动从 DB 加载，确保服务重启后会话不失效。
"""

import os
import secrets
import logging
from typing import Optional

from app.core.database import get_mongo_db

logger = logging.getLogger("app.secret_service")

# 集合名
_COLLECTION = "system_secrets"

# 需要自动管理的密钥及其默认长度
_MANAGED_SECRETS = {
    "jwt_secret": 48,
    "csrf_secret": 48,
}


class SecretService:
    """安全密钥管理服务"""

    @staticmethod
    async def ensure_secrets() -> dict[str, str]:
        """确保所有受管密钥都已生成并持久化。

        首次启动时自动生成，后续从 DB 加载。
        同时将密钥写入 os.environ，供 auth 中间件等使用。
        """
        db = get_mongo_db()
        collection = db[_COLLECTION]
        result = {}

        for name, length in _MANAGED_SECRETS.items():
            doc = await collection.find_one({"name": name})
            if doc and doc.get("value"):
                result[name] = doc["value"]
                logger.debug(f"从 DB 加载密钥: {name}")
            else:
                value = secrets.token_urlsafe(length)
                await collection.update_one(
                    {"name": name},
                    {"$set": {"name": name, "value": value}},
                    upsert=True,
                )
                result[name] = value
                logger.info(f"自动生成并持久化密钥: {name}")

        # 同步到 os.environ，供依赖环境变量的代码使用
        env_map = {"jwt_secret": "JWT_SECRET", "csrf_secret": "CSRF_SECRET"}
        for name, env_key in env_map.items():
            if name in result:
                os.environ[env_key] = result[name]

        logger.info(f"安全密钥管理完成，共 {len(result)} 个密钥已就绪")
        return result

    @staticmethod
    async def get_secret(name: str) -> Optional[str]:
        """从 DB 读取指定密钥"""
        db = get_mongo_db()
        doc = await db[_COLLECTION].find_one({"name": name})
        return doc.get("value") if doc else None

    @staticmethod
    async def rotate_secret(name: str) -> str:
        """重新生成并更新密钥"""
        if name not in _MANAGED_SECRETS:
            raise ValueError(f"未知密钥: {name}")

        length = _MANAGED_SECRETS[name]
        new_value = secrets.token_urlsafe(length)

        db = get_mongo_db()
        await db[_COLLECTION].update_one(
            {"name": name},
            {"$set": {"value": new_value}},
            upsert=True,
        )

        # 同步到 os.environ
        env_map = {"jwt_secret": "JWT_SECRET", "csrf_secret": "CSRF_SECRET"}
        env_key = env_map.get(name)
        if env_key:
            os.environ[env_key] = new_value

        logger.warning(f"密钥已轮换: {name}")
        return new_value
