
import json
import logging
import hashlib
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional
from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.core.database import db_manager
from app.core.config import settings
from app.utils.time_utils import now_utc

logger = logging.getLogger(__name__)

# 默认管理员用户
DEFAULT_ADMIN = {
    "username": "admin",
    "password": "admin123",
    "email": "admin@tradingagents.cn"
}

# 配置集合列表
CONFIG_COLLECTIONS = [
    "system_configs",
    "users",
    "llm_providers",
    "market_categories",
    "user_tags",
    "datasource_groupings",
    "platform_configs",
    "user_configs",
    "model_catalog"
]

class SystemInitService:
    """系统初始化服务
    
    负责在系统启动时检查数据库状态，并在需要时导入初始配置和创建默认用户。
    """
    
    @staticmethod
    def hash_password(password: str) -> str:
        """使用 SHA256 哈希密码（与系统一致）"""
        return hashlib.sha256(password.encode()).hexdigest()

    @staticmethod
    def convert_to_bson(data: Any) -> Any:
        """将 JSON 数据转换为 BSON 兼容格式"""
        if isinstance(data, dict):
            result = {}
            for key, value in data.items():
                # 处理 ObjectId
                if key == "_id" or key.endswith("_id"):
                    if isinstance(value, str) and len(value) == 24:
                        try:
                            result[key] = ObjectId(value)
                            continue
                        except:
                            pass
                
                # 处理日期时间
                if key.endswith("_at") or key in ["created_at", "updated_at", "last_login", "added_at"]:
                    if isinstance(value, str):
                        try:
                            # 处理 ISO 格式时间字符串
                            result[key] = datetime.fromisoformat(value.replace('Z', '+00:00'))
                            continue
                        except:
                            pass
                
                result[key] = SystemInitService.convert_to_bson(value)
            return result
        
        elif isinstance(data, list):
            return [SystemInitService.convert_to_bson(item) for item in data]
        
        else:
            return data

    @classmethod
    async def initialize_system(cls):
        """初始化系统"""
        try:
            logger.info("🚀 开始检查系统初始化状态...")
            
            db = db_manager.mongo_db
            if db is None:
                logger.error("❌ 数据库未连接，跳过初始化")
                return

            # 1. 检查是否需要导入配置
            # 我们通过检查 users 集合是否为空来判断是否是首次运行
            # 或者检查 system_configs 是否存在
            users_count = await db.users.count_documents({})
            
            if users_count > 0:
                logger.info(f"✅ 系统已初始化 (发现 {users_count} 个用户)，跳过数据导入")
            else:
                logger.info("🆕 检测到空数据库，准备执行初始化...")
                await cls._import_initial_data(db)
                
            # 2. 确保默认管理员存在 (即使数据导入失败，也要保证有管理员)
            await cls._ensure_default_admin(db)
            
            logger.info("✨ 系统初始化检查完成")
            
        except Exception as e:
            logger.error(f"❌ 系统初始化过程中发生错误: {e}", exc_info=True)

    @classmethod
    async def _import_initial_data(cls, db: AsyncIOMotorDatabase):
        """导入初始数据"""
        # 寻找导出文件
        # 路径策略：
        # 1. 检查 /app/install (Docker环境)
        # 2. 检查项目根目录/install (开发环境)
        
        project_root = Path(__file__).parent.parent.parent
        install_dirs = [
            Path("/app/install"),
            project_root / "install"
        ]
        
        export_file = None
        
        for install_dir in install_dirs:
            if install_dir.exists():
                # 查找 database_export_config_*.json 文件
                config_files = list(install_dir.glob("database_export_config_*.json"))
                if config_files:
                    # 使用最新的文件
                    export_file = sorted(config_files)[-1]
                    logger.info(f"📂 找到初始配置文件: {export_file}")
                    break
        
        if not export_file:
            logger.info("ℹ️ 未找到外部数据导入文件 (install/database_export_config_*.json)，将仅执行基础初始化")
            return

        try:
            # 读取并解析 JSON
            # 注意：JSON读取是同步IO，但只在启动时执行一次，影响不大
            with open(export_file, 'r', encoding='utf-8') as f:
                data_wrapper = json.load(f)
            
            if "data" not in data_wrapper:
                logger.error("❌ 配置文件格式错误: 缺少 'data' 字段")
                return
                
            data = data_wrapper["data"]
            
            # 导入集合
            collections_to_import = [c for c in CONFIG_COLLECTIONS if c in data]
            
            logger.info(f"📋 准备导入 {len(collections_to_import)} 个集合")
            
            total_inserted = 0
            
            for col_name in collections_to_import:
                documents = data[col_name]
                if not documents:
                    continue
                    
                # 转换数据格式
                converted_docs = cls.convert_to_bson(documents)
                
                # 批量插入
                collection = db[col_name]
                
                # 再次检查集合是否为空，避免重复插入
                # 只有当集合完全为空时才导入，确保不会覆盖现有数据
                if await collection.count_documents({}) == 0:
                    result = await collection.insert_many(converted_docs)
                    inserted_count = len(result.inserted_ids)
                    total_inserted += inserted_count
                    logger.info(f"   - {col_name}: 导入 {inserted_count} 条数据")
                else:
                    logger.info(f"   - {col_name}: 集合非空，跳过导入")
            
            logger.info(f"✅ 数据导入完成，共插入 {total_inserted} 条文档")
            
        except Exception as e:
            logger.error(f"❌ 导入初始数据失败: {e}")

    @classmethod
    async def _ensure_default_admin(cls, db: AsyncIOMotorDatabase):
        """确保默认管理员存在"""
        users_collection = db.users
        
        existing_user = await users_collection.find_one({"username": DEFAULT_ADMIN["username"]})
        
        if existing_user:
            # 用户已存在，不做任何事
            return
            
        logger.info(f"👤 创建默认管理员用户: {DEFAULT_ADMIN['username']}")
        
        # 创建用户文档
        user_doc = {
            "username": DEFAULT_ADMIN["username"],
            "email": DEFAULT_ADMIN["email"],
            "hashed_password": cls.hash_password(DEFAULT_ADMIN["password"]),
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
        
        await users_collection.insert_one(user_doc)
        logger.info("✅ 默认管理员创建成功")
