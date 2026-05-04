"""
数据库配置管理与连接测试服务
"""

import time
import os
import logging
from typing import List, Optional, Dict, Any

from app.core.database import get_mongo_db
from app.models.config import DatabaseConfig
from app.utils.timezone import now_tz

logger = logging.getLogger(__name__)


class DatabaseService:
    """数据库配置管理与连接测试"""

    def __init__(self, db_manager=None):
        self.db = None
        self.db_manager = db_manager

    async def _get_db(self):
        """获取数据库连接"""
        if self.db is None:
            if self.db_manager and self.db_manager.mongo_db is not None:
                self.db = self.db_manager.mongo_db
            else:
                self.db = get_mongo_db()
        return self.db

    async def _get_system_config(self):
        """从数据库获取系统配置（内部使用）"""
        try:
            from app.models.config import SystemConfig

            db = await self._get_db()
            config_collection = db.system_configs
            config_data = await config_collection.find_one(
                {"is_active": True},
                sort=[("version", -1)]
            )
            if config_data:
                config_data.setdefault('config_name', config_data.get('config_name', 'bridged'))
                config_data.setdefault('config_type', config_data.get('config_type', 'system'))
                return SystemConfig(**config_data)
            return None
        except Exception as e:
            logger.error(f"❌ 获取系统配置失败: {e}")
            return None

    async def _save_system_config(self, config) -> bool:
        """保存系统配置（内部使用）"""
        try:
            from app.utils.timezone import now_tz

            db = await self._get_db()
            config_collection = db.system_configs

            config.updated_at = now_tz()
            config.version += 1

            await config_collection.update_many(
                {"is_active": True},
                {"$set": {"is_active": False}}
            )

            config_dict = config.model_dump(by_alias=True)
            if '_id' in config_dict:
                del config_dict['_id']

            await config_collection.insert_one(config_dict)
            return True
        except Exception as e:
            logger.error(f"❌ 保存系统配置失败: {e}")
            return False

    # ==================== 数据库配置管理 ====================

    async def add_database_config(self, db_config: DatabaseConfig) -> bool:
        """添加数据库配置"""
        try:
            logger.info(f"➕ 添加数据库配置: {db_config.name}")

            config = await self._get_system_config()
            if not config:
                logger.error("❌ 系统配置为空")
                return False

            # 检查是否已存在同名配置
            for existing_db in config.database_configs:
                if existing_db.name == db_config.name:
                    logger.error(f"❌ 数据库配置 '{db_config.name}' 已存在")
                    return False

            # 添加新配置
            config.database_configs.append(db_config)

            # 保存配置
            result = await self._save_system_config(config)
            if result:
                logger.info(f"✅ 数据库配置 '{db_config.name}' 添加成功")
            else:
                logger.error(f"❌ 数据库配置 '{db_config.name}' 添加失败")

            return result

        except Exception as e:
            logger.error(f"❌ 添加数据库配置失败: {e}")
            import traceback
            traceback.print_exc()
            return False

    async def update_database_config(self, db_config: DatabaseConfig) -> bool:
        """更新数据库配置"""
        try:
            logger.info(f"🔄 更新数据库配置: {db_config.name}")

            config = await self._get_system_config()
            if not config:
                logger.error("❌ 系统配置为空")
                return False

            # 查找并更新配置
            found = False
            for i, existing_db in enumerate(config.database_configs):
                if existing_db.name == db_config.name:
                    config.database_configs[i] = db_config
                    found = True
                    break

            if not found:
                logger.error(f"❌ 数据库配置 '{db_config.name}' 不存在")
                return False

            # 保存配置
            result = await self._save_system_config(config)
            if result:
                logger.info(f"✅ 数据库配置 '{db_config.name}' 更新成功")
            else:
                logger.error(f"❌ 数据库配置 '{db_config.name}' 更新失败")

            return result

        except Exception as e:
            logger.error(f"❌ 更新数据库配置失败: {e}")
            import traceback
            traceback.print_exc()
            return False

    async def delete_database_config(self, db_name: str) -> bool:
        """删除数据库配置"""
        try:
            logger.info(f"🗑️ 删除数据库配置: {db_name}")

            config = await self._get_system_config()
            if not config:
                logger.error("❌ 系统配置为空")
                return False

            # 记录原始数量
            original_count = len(config.database_configs)

            # 删除指定配置
            config.database_configs = [
                db for db in config.database_configs
                if db.name != db_name
            ]

            new_count = len(config.database_configs)

            if new_count == original_count:
                logger.error(f"❌ 数据库配置 '{db_name}' 不存在")
                return False

            # 保存配置
            result = await self._save_system_config(config)
            if result:
                logger.info(f"✅ 数据库配置 '{db_name}' 删除成功")
            else:
                logger.error(f"❌ 数据库配置 '{db_name}' 删除失败")

            return result

        except Exception as e:
            logger.error(f"❌ 删除数据库配置失败: {e}")
            import traceback
            traceback.print_exc()
            return False

    async def get_database_config(self, db_name: str) -> Optional[DatabaseConfig]:
        """获取指定的数据库配置"""
        try:
            config = await self._get_system_config()
            if not config:
                return None

            for db in config.database_configs:
                if db.name == db_name:
                    return db

            return None

        except Exception as e:
            logger.error(f"❌ 获取数据库配置失败: {e}")
            return None

    async def get_database_configs(self) -> List[DatabaseConfig]:
        """获取所有数据库配置"""
        try:
            config = await self._get_system_config()
            if not config:
                return []

            return config.database_configs

        except Exception as e:
            logger.error(f"❌ 获取数据库配置列表失败: {e}")
            return []

    # ==================== 数据库连接测试 ====================

    async def test_database_config(self, db_config: DatabaseConfig) -> Dict[str, Any]:
        """测试数据库配置 - 真实连接测试"""
        start_time = time.time()
        try:
            db_type = db_config.type.value if hasattr(db_config.type, 'value') else str(db_config.type)

            logger.info(f"🧪 测试数据库配置: {db_config.name} ({db_type})")
            logger.info(f"📍 连接地址: {db_config.host}:{db_config.port}")

            # 根据不同的数据库类型进行测试
            if db_type == "mongodb":
                try:
                    from motor.motor_asyncio import AsyncIOMotorClient

                    # 🔥 优先使用环境变量中的完整连接信息（包括host、用户名、密码）
                    host = db_config.host
                    port = db_config.port
                    username = db_config.username
                    password = db_config.password
                    database = db_config.database
                    auth_source = None
                    used_env_config = False

                    # 检测是否在 Docker 环境中
                    is_docker = os.path.exists('/.dockerenv') or os.getenv('DOCKER_CONTAINER') == 'true'

                    # 如果配置中没有用户名密码，尝试从环境变量获取完整配置
                    if not username or not password:
                        env_host = os.getenv('MONGODB_HOST')
                        env_port = os.getenv('MONGODB_PORT')
                        env_username = os.getenv('MONGODB_USERNAME')
                        env_password = os.getenv('MONGODB_PASSWORD')
                        env_auth_source = os.getenv('MONGODB_AUTH_SOURCE', 'admin')

                        if env_username and env_password:
                            username = env_username
                            password = env_password
                            auth_source = env_auth_source
                            used_env_config = True

                            # 如果环境变量中有 host 配置，也使用它
                            if env_host:
                                host = env_host
                                # 🔥 Docker 环境下，将 localhost 替换为 mongodb
                                if is_docker and host == 'localhost':
                                    host = 'mongodb'
                                    logger.info(f"🐳 检测到 Docker 环境，将 host 从 localhost 改为 mongodb")

                            if env_port:
                                port = int(env_port)

                            logger.info(f"🔑 使用环境变量中的 MongoDB 配置 (host={host}, port={port}, authSource={auth_source})")

                    # 如果配置中没有数据库名，尝试从环境变量获取
                    if not database:
                        env_database = os.getenv('MONGODB_DATABASE')
                        if env_database:
                            database = env_database
                            logger.info(f"📦 使用环境变量中的数据库名: {database}")

                    # 从连接参数中获取 authSource（如果有）
                    if not auth_source and db_config.connection_params:
                        auth_source = db_config.connection_params.get('authSource')

                    # 构建连接字符串
                    if username and password:
                        connection_string = f"mongodb://{username}:{password}@{host}:{port}"
                    else:
                        connection_string = f"mongodb://{host}:{port}"

                    if database:
                        connection_string += f"/{database}"

                    # 添加连接参数
                    params_list = []

                    # 如果有 authSource，添加到参数中
                    if auth_source:
                        params_list.append(f"authSource={auth_source}")

                    # 添加其他连接参数
                    if db_config.connection_params:
                        for k, v in db_config.connection_params.items():
                            if k != 'authSource':  # authSource 已经添加过了
                                params_list.append(f"{k}={v}")

                    if params_list:
                        connection_string += f"?{'&'.join(params_list)}"

                    logger.info(f"🔗 连接字符串: {connection_string.replace(password or '', '***') if password else connection_string}")

                    # 创建客户端并测试连接
                    client = AsyncIOMotorClient(
                        connection_string,
                        serverSelectionTimeoutMS=5000  # 5秒超时
                    )

                    # 如果指定了数据库，测试该数据库的访问权限
                    if database:
                        # 测试指定数据库的访问（不需要管理员权限）
                        db = client[database]
                        # 尝试列出集合（如果没有权限会报错）
                        collections = await db.list_collection_names()
                        test_result = f"数据库 '{database}' 可访问，包含 {len(collections)} 个集合"
                    else:
                        # 如果没有指定数据库，只执行 ping 命令
                        await client.admin.command('ping')
                        test_result = "连接成功"

                    response_time = time.time() - start_time

                    # 关闭连接
                    client.close()

                    return {
                        "success": True,
                        "message": f"成功连接到 MongoDB 数据库",
                        "response_time": response_time,
                        "details": {
                            "type": db_type,
                            "host": host,
                            "port": port,
                            "database": database,
                            "auth_source": auth_source,
                            "test_result": test_result,
                            "used_env_config": used_env_config
                        }
                    }
                except ImportError:
                    return {
                        "success": False,
                        "message": "Motor 库未安装，请运行: pip install motor",
                        "response_time": time.time() - start_time,
                        "details": None
                    }
                except Exception as e:
                    error_msg = str(e)
                    logger.error(f"❌ MongoDB 连接测试失败: {error_msg}")

                    if "Authentication failed" in error_msg or "auth failed" in error_msg.lower():
                        message = "认证失败，请检查用户名和密码"
                    elif "requires authentication" in error_msg.lower():
                        message = "需要认证，请配置用户名和密码"
                    elif "not authorized" in error_msg.lower():
                        message = "权限不足，请检查用户权限配置"
                    elif "Connection refused" in error_msg:
                        message = "连接被拒绝，请检查主机地址和端口"
                    elif "timed out" in error_msg.lower():
                        message = "连接超时，请检查网络和防火墙设置"
                    elif "No servers found" in error_msg:
                        message = "找不到服务器，请检查主机地址和端口"
                    else:
                        message = f"连接失败: {error_msg}"

                    return {
                        "success": False,
                        "message": message,
                        "response_time": time.time() - start_time,
                        "details": None
                    }

            elif db_type == "redis":
                try:
                    import redis.asyncio as aioredis

                    # 🔥 优先使用环境变量中的完整 Redis 配置（包括host、密码）
                    host = db_config.host
                    port = db_config.port
                    password = db_config.password
                    database = db_config.database
                    used_env_config = False

                    # 检测是否在 Docker 环境中
                    is_docker = os.path.exists('/.dockerenv') or os.getenv('DOCKER_CONTAINER') == 'true'

                    # 如果配置中没有密码，尝试从环境变量获取完整配置
                    if not password:
                        env_host = os.getenv('REDIS_HOST')
                        env_port = os.getenv('REDIS_PORT')
                        env_password = os.getenv('REDIS_PASSWORD')

                        if env_password:
                            password = env_password
                            used_env_config = True

                            # 如果环境变量中有 host 配置，也使用它
                            if env_host:
                                host = env_host
                                # 🔥 Docker 环境下，将 localhost 替换为 redis
                                if is_docker and host == 'localhost':
                                    host = 'redis'
                                    logger.info(f"🐳 检测到 Docker 环境，将 Redis host 从 localhost 改为 redis")

                            if env_port:
                                port = int(env_port)

                            logger.info(f"🔑 使用环境变量中的 Redis 配置 (host={host}, port={port})")

                    # 如果配置中没有数据库编号，尝试从环境变量获取
                    if database is None:
                        env_db = os.getenv('REDIS_DB')
                        if env_db:
                            database = int(env_db)
                            logger.info(f"📦 使用环境变量中的 Redis 数据库编号: {database}")

                    # 构建连接参数
                    redis_params = {
                        "host": host,
                        "port": port,
                        "decode_responses": True,
                        "socket_connect_timeout": 5
                    }

                    if password:
                        redis_params["password"] = password

                    if database is not None:
                        redis_params["db"] = int(database)

                    # 创建连接并测试
                    redis_client = await aioredis.from_url(
                        f"redis://{host}:{port}",
                        **redis_params
                    )

                    # 执行 PING 命令
                    await redis_client.ping()

                    # 获取服务器信息
                    info = await redis_client.info("server")

                    response_time = time.time() - start_time

                    # 关闭连接
                    await redis_client.close()

                    return {
                        "success": True,
                        "message": f"成功连接到 Redis 数据库",
                        "response_time": response_time,
                        "details": {
                            "type": db_type,
                            "host": host,
                            "port": port,
                            "database": database,
                            "redis_version": info.get("redis_version", "unknown"),
                            "used_env_config": used_env_config
                        }
                    }
                except ImportError:
                    return {
                        "success": False,
                        "message": "Redis 库未安装，请运行: pip install redis",
                        "response_time": time.time() - start_time,
                        "details": None
                    }
                except Exception as e:
                    error_msg = str(e)
                    if "WRONGPASS" in error_msg or "Authentication" in error_msg:
                        message = "认证失败，请检查密码"
                    elif "Connection refused" in error_msg:
                        message = "连接被拒绝，请检查主机地址和端口"
                    elif "timed out" in error_msg.lower():
                        message = "连接超时，请检查网络和防火墙设置"
                    else:
                        message = f"连接失败: {error_msg}"

                    return {
                        "success": False,
                        "message": message,
                        "response_time": time.time() - start_time,
                        "details": None
                    }

            elif db_type == "mysql":
                try:
                    import aiomysql

                    # 创建连接
                    conn = await aiomysql.connect(
                        host=db_config.host,
                        port=db_config.port,
                        user=db_config.username,
                        password=db_config.password,
                        db=db_config.database,
                        connect_timeout=5
                    )

                    # 执行测试查询
                    async with conn.cursor() as cursor:
                        await cursor.execute("SELECT VERSION()")
                        version = await cursor.fetchone()

                    response_time = time.time() - start_time

                    # 关闭连接
                    conn.close()

                    return {
                        "success": True,
                        "message": f"成功连接到 MySQL 数据库",
                        "response_time": response_time,
                        "details": {
                            "type": db_type,
                            "host": db_config.host,
                            "port": db_config.port,
                            "database": db_config.database,
                            "version": version[0] if version else "unknown"
                        }
                    }
                except ImportError:
                    return {
                        "success": False,
                        "message": "aiomysql 库未安装，请运行: pip install aiomysql",
                        "response_time": time.time() - start_time,
                        "details": None
                    }
                except Exception as e:
                    error_msg = str(e)
                    if "Access denied" in error_msg:
                        message = "访问被拒绝，请检查用户名和密码"
                    elif "Unknown database" in error_msg:
                        message = f"数据库 '{db_config.database}' 不存在"
                    elif "Can't connect" in error_msg:
                        message = "无法连接，请检查主机地址和端口"
                    else:
                        message = f"连接失败: {error_msg}"

                    return {
                        "success": False,
                        "message": message,
                        "response_time": time.time() - start_time,
                        "details": None
                    }

            elif db_type == "postgresql":
                try:
                    import asyncpg

                    # 创建连接
                    conn = await asyncpg.connect(
                        host=db_config.host,
                        port=db_config.port,
                        user=db_config.username,
                        password=db_config.password,
                        database=db_config.database,
                        timeout=5
                    )

                    # 执行测试查询
                    version = await conn.fetchval("SELECT version()")

                    response_time = time.time() - start_time

                    # 关闭连接
                    await conn.close()

                    return {
                        "success": True,
                        "message": f"成功连接到 PostgreSQL 数据库",
                        "response_time": response_time,
                        "details": {
                            "type": db_type,
                            "host": db_config.host,
                            "port": db_config.port,
                            "database": db_config.database,
                            "version": version.split()[1] if version else "unknown"
                        }
                    }
                except ImportError:
                    return {
                        "success": False,
                        "message": "asyncpg 库未安装，请运行: pip install asyncpg",
                        "response_time": time.time() - start_time,
                        "details": None
                    }
                except Exception as e:
                    error_msg = str(e)
                    if "password authentication failed" in error_msg:
                        message = "密码认证失败，请检查用户名和密码"
                    elif "does not exist" in error_msg:
                        message = f"数据库 '{db_config.database}' 不存在"
                    elif "Connection refused" in error_msg:
                        message = "连接被拒绝，请检查主机地址和端口"
                    else:
                        message = f"连接失败: {error_msg}"

                    return {
                        "success": False,
                        "message": message,
                        "response_time": time.time() - start_time,
                        "details": None
                    }

            elif db_type == "sqlite":
                try:
                    import aiosqlite

                    # SQLite 使用文件路径，不需要 host/port
                    db_path = db_config.database or db_config.host

                    # 创建连接
                    async with aiosqlite.connect(db_path, timeout=5) as conn:
                        # 执行测试查询
                        async with conn.execute("SELECT sqlite_version()") as cursor:
                            version = await cursor.fetchone()

                    response_time = time.time() - start_time

                    return {
                        "success": True,
                        "message": f"成功连接到 SQLite 数据库",
                        "response_time": response_time,
                        "details": {
                            "type": db_type,
                            "database": db_path,
                            "version": version[0] if version else "unknown"
                        }
                    }
                except ImportError:
                    return {
                        "success": False,
                        "message": "aiosqlite 库未安装，请运行: pip install aiosqlite",
                        "response_time": time.time() - start_time,
                        "details": None
                    }
                except Exception as e:
                    return {
                        "success": False,
                        "message": f"连接失败: {str(e)}",
                        "response_time": time.time() - start_time,
                        "details": None
                    }

            else:
                return {
                    "success": False,
                    "message": f"不支持的数据库类型: {db_type}",
                    "response_time": time.time() - start_time,
                    "details": None
                }

        except Exception as e:
            response_time = time.time() - start_time
            logger.error(f"❌ 测试数据库配置失败: {e}")
            return {
                "success": False,
                "message": f"连接失败: {str(e)}",
                "response_time": response_time,
                "details": None
            }
