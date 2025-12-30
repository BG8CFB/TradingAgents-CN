"""
用户服务 - 基于数据库的用户管理（异步版本）
"""

import hashlib
import time
from datetime import datetime
from typing import Optional, Dict, Any, List
from bson import ObjectId

from app.core.config import settings
from app.models.user import User, UserCreate, UserUpdate, UserResponse
from tradingagents.utils.time_utils import now_utc

from motor.motor_asyncio import AsyncIOMotorDatabase

# 尝试导入日志管理器
try:
    from tradingagents.utils.logging_manager import get_logger
except ImportError:
    import logging
    def get_logger(name: str) -> logging.Logger:
        return logging.getLogger(name)

logger = get_logger('user_service')


class UserService:
    """用户服务类 - 使用异步数据库客户端"""

    def __init__(self):
        self.db: Optional[AsyncIOMotorDatabase] = None

    def set_database(self, db: AsyncIOMotorDatabase):
        """设置数据库实例"""
        self.db = db

    @staticmethod
    def hash_password(password: str) -> str:
        """密码哈希"""
        return hashlib.sha256(password.encode()).hexdigest()

    @staticmethod
    def verify_password(plain_password: str, hashed_password: str) -> bool:
        """验证密码"""
        return UserService.hash_password(plain_password) == hashed_password

    async def create_user(self, user_data: UserCreate) -> Optional[User]:
        """创建用户"""
        try:
            if self.db is None:
                logger.error("数据库未初始化")
                return None

            users_collection = self.db.users

            existing_user = await users_collection.find_one({"username": user_data.username})
            if existing_user:
                logger.warning(f"用户名已存在: {user_data.username}")
                return None

            existing_email = await users_collection.find_one({"email": user_data.email})
            if existing_email:
                logger.warning(f"邮箱已存在: {user_data.email}")
                return None

            user_doc = {
                "username": user_data.username,
                "email": user_data.email,
                "hashed_password": self.hash_password(user_data.password),
                "is_active": True,
                "is_verified": False,
                "is_admin": False,
                "created_at": now_utc(),
                "updated_at": now_utc(),
                "last_login": None,
                "preferences": {
                    "default_market": "A股",
                    "default_depth": "3",
                    "default_analysts": [],
                    "auto_refresh": True,
                    "refresh_interval": 30,
                    "ui_theme": "light",
                    "sidebar_width": 240,
                    "language": "zh-CN",
                    "notifications_enabled": True,
                    "email_notifications": False,
                    "desktop_notifications": True,
                    "analysis_complete_notification": True,
                    "system_maintenance_notification": True
                },
                "daily_quota": 1000,
                "concurrent_limit": 3,
                "total_analyses": 0,
                "successful_analyses": 0,
                "failed_analyses": 0,
                "favorite_stocks": []
            }

            result = await users_collection.insert_one(user_doc)
            user_doc["_id"] = result.inserted_id

            logger.info(f"✅ 用户创建成功: {user_data.username}")
            return User(**user_doc)

        except Exception as e:
            logger.error(f"❌ 创建用户失败: {e}")
            return None

    async def authenticate_user(self, username: str, password: str) -> Optional[User]:
        """用户认证"""
        try:
            logger.info(f"🔍 [authenticate_user] 开始认证用户: {username}")

            if self.db is None:
                logger.error("数据库未初始化")
                return None

            users_collection = self.db.users

            user_doc = await users_collection.find_one({"username": username})
            logger.info(f"🔍 [authenticate_user] 数据库查询结果: {'找到用户' if user_doc else '用户不存在'}")

            if not user_doc:
                logger.warning(f"❌ [authenticate_user] 用户不存在: {username}")
                return None

            logger.info(f"🔍 [authenticate_user] 用户信息: username={user_doc.get('username')}, email={user_doc.get('email')}, is_active={user_doc.get('is_active')}")

            input_password_hash = self.hash_password(password)
            stored_password_hash = user_doc["hashed_password"]
            logger.info(f"🔍 [authenticate_user] 密码哈希对比:")
            logger.info(f"   输入密码哈希: {input_password_hash[:20]}...")
            logger.info(f"   存储密码哈希: {stored_password_hash[:20]}...")
            logger.info(f"   哈希匹配: {input_password_hash == stored_password_hash}")

            if not self.verify_password(password, user_doc["hashed_password"]):
                logger.warning(f"❌ [authenticate_user] 密码错误: {username}")
                return None

            if not user_doc.get("is_active", True):
                logger.warning(f"❌ [authenticate_user] 用户已禁用: {username}")
                return None

            await users_collection.update_one(
                {"_id": user_doc["_id"]},
                {"$set": {"last_login": now_utc()}}
            )

            logger.info(f"✅ [authenticate_user] 用户认证成功: {username}")
            return User(**user_doc)

        except Exception as e:
            logger.error(f"❌ 用户认证失败: {e}")
            return None

    async def get_user_by_username(self, username: str) -> Optional[User]:
        """根据用户名获取用户"""
        try:
            if self.db is None:
                logger.error("数据库未初始化")
                return None

            user_doc = await self.db.users.find_one({"username": username})
            if user_doc:
                return User(**user_doc)
            return None
        except Exception as e:
            logger.error(f"❌ 获取用户失败: {e}")
            return None

    async def get_user_by_id(self, user_id: str) -> Optional[User]:
        """根据用户ID获取用户"""
        try:
            if self.db is None:
                logger.error("数据库未初始化")
                return None

            if not ObjectId.is_valid(user_id):
                return None

            user_doc = await self.db.users.find_one({"_id": ObjectId(user_id)})
            if user_doc:
                return User(**user_doc)
            return None
        except Exception as e:
            logger.error(f"❌ 获取用户失败: {e}")
            return None

    async def update_user(self, username: str, user_data: UserUpdate) -> Optional[User]:
        """更新用户信息"""
        try:
            if self.db is None:
                logger.error("数据库未初始化")
                return None

            users_collection = self.db.users
            update_data = {"updated_at": now_utc()}

            if user_data.email:
                existing_email = await users_collection.find_one({
                    "email": user_data.email,
                    "username": {"$ne": username}
                })
                if existing_email:
                    logger.warning(f"邮箱已被使用: {user_data.email}")
                    return None
                update_data["email"] = user_data.email

            if user_data.preferences:
                update_data["preferences"] = user_data.preferences.model_dump()

            if user_data.daily_quota is not None:
                update_data["daily_quota"] = user_data.daily_quota

            if user_data.concurrent_limit is not None:
                update_data["concurrent_limit"] = user_data.concurrent_limit

            result = await users_collection.update_one(
                {"username": username},
                {"$set": update_data}
            )

            if result.modified_count > 0:
                logger.info(f"✅ 用户信息更新成功: {username}")
                return await self.get_user_by_username(username)
            else:
                logger.warning(f"用户不存在或无需更新: {username}")
                return None

        except Exception as e:
            logger.error(f"❌ 更新用户信息失败: {e}")
            return None

    async def change_password(self, username: str, old_password: str, new_password: str) -> bool:
        """修改密码"""
        try:
            user = await self.authenticate_user(username, old_password)
            if not user:
                logger.warning(f"旧密码验证失败: {username}")
                return False

            if self.db is None:
                logger.error("数据库未初始化")
                return False

            new_hashed_password = self.hash_password(new_password)
            result = await self.db.users.update_one(
                {"username": username},
                {
                    "$set": {
                        "hashed_password": new_hashed_password,
                        "updated_at": now_utc()
                    }
                }
            )

            if result.modified_count > 0:
                logger.info(f"✅ 密码修改成功: {username}")
                return True
            else:
                logger.error(f"❌ 密码修改失败: {username}")
                return False

        except Exception as e:
            logger.error(f"❌ 修改密码失败: {e}")
            return False

    async def reset_password(self, username: str, new_password: str) -> bool:
        """重置密码（管理员操作）"""
        try:
            if self.db is None:
                logger.error("数据库未初始化")
                return False

            new_hashed_password = self.hash_password(new_password)
            result = await self.db.users.update_one(
                {"username": username},
                {
                    "$set": {
                        "hashed_password": new_hashed_password,
                        "updated_at": now_utc()
                    }
                }
            )

            if result.modified_count > 0:
                logger.info(f"✅ 密码重置成功: {username}")
                return True
            else:
                logger.error(f"❌ 密码重置失败: {username}")
                return False

        except Exception as e:
            logger.error(f"❌ 重置密码失败: {e}")
            return False

    async def create_admin_user(self, username: str = "admin", password: str = "admin123", email: str = "admin@tradingagents.cn") -> Optional[User]:
        """创建管理员用户"""
        try:
            if self.db is None:
                logger.error("数据库未初始化")
                return None

            users_collection = self.db.users

            existing_admin = await users_collection.find_one({"username": username})
            if existing_admin:
                logger.info(f"管理员用户已存在: {username}")
                return User(**existing_admin)

            admin_doc = {
                "username": username,
                "email": email,
                "hashed_password": self.hash_password(password),
                "is_active": True,
                "is_verified": True,
                "is_admin": True,
                "created_at": now_utc(),
                "updated_at": now_utc(),
                "last_login": None,
                "preferences": {
                    "default_market": "A股",
                    "default_depth": "深度",
                    "ui_theme": "light",
                    "language": "zh-CN",
                    "notifications_enabled": True,
                    "email_notifications": False
                },
                "daily_quota": 10000,
                "concurrent_limit": 10,
                "total_analyses": 0,
                "successful_analyses": 0,
                "failed_analyses": 0,
                "favorite_stocks": []
            }

            result = await users_collection.insert_one(admin_doc)
            admin_doc["_id"] = result.inserted_id

            logger.info(f"✅ 管理员用户创建成功: {username}")
            logger.info(f"   密码: {password}")
            logger.info("   ⚠️  请立即修改默认密码！")

            return User(**admin_doc)

        except Exception as e:
            logger.error(f"❌ 创建管理员用户失败: {e}")
            return None

    async def list_users(self, skip: int = 0, limit: int = 100) -> List[UserResponse]:
        """获取用户列表"""
        try:
            if self.db is None:
                logger.error("数据库未初始化")
                return []

            cursor = self.db.users.find().skip(skip).limit(limit)
            users = []

            async for user_doc in cursor:
                user = User(**user_doc)
                users.append(UserResponse(
                    id=str(user.id),
                    username=user.username,
                    email=user.email,
                    is_active=user.is_active,
                    is_verified=user.is_verified,
                    created_at=user.created_at,
                    last_login=user.last_login,
                    preferences=user.preferences,
                    daily_quota=user.daily_quota,
                    concurrent_limit=user.concurrent_limit,
                    total_analyses=user.total_analyses,
                    successful_analyses=user.successful_analyses,
                    failed_analyses=user.failed_analyses
                ))

            return users

        except Exception as e:
            logger.error(f"❌ 获取用户列表失败: {e}")
            return []

    async def deactivate_user(self, username: str) -> bool:
        """禁用用户"""
        try:
            if self.db is None:
                logger.error("数据库未初始化")
                return False

            result = await self.db.users.update_one(
                {"username": username},
                {
                    "$set": {
                        "is_active": False,
                        "updated_at": now_utc()
                    }
                }
            )

            if result.modified_count > 0:
                logger.info(f"✅ 用户已禁用: {username}")
                return True
            else:
                logger.warning(f"用户不存在: {username}")
                return False

        except Exception as e:
            logger.error(f"❌ 禁用用户失败: {e}")
            return False

    async def activate_user(self, username: str) -> bool:
        """激活用户"""
        try:
            if self.db is None:
                logger.error("数据库未初始化")
                return False

            result = await self.db.users.update_one(
                {"username": username},
                {
                    "$set": {
                        "is_active": True,
                        "updated_at": now_utc()
                    }
                }
            )

            if result.modified_count > 0:
                logger.info(f"✅ 用户已激活: {username}")
                return True
            else:
                logger.warning(f"用户不存在: {username}")
                return False

        except Exception as e:
            logger.error(f"❌ 激活用户失败: {e}")
            return False


# 全局用户服务实例
user_service = UserService()
