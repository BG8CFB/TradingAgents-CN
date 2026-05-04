"""
系统配置与导入导出管理服务
"""

import logging
from typing import List, Optional, Dict, Any

from app.core.database import get_mongo_db
from app.core.unified_config import unified_config
from app.models.config import (
    SystemConfig, LLMConfig, DataSourceConfig, DatabaseConfig,
    ModelProvider, DataSourceType, DatabaseType
)
from app.utils.timezone import now_tz

logger = logging.getLogger(__name__)


class SystemService:
    """系统配置管理与导入导出"""

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

    # ==================== 系统配置管理 ====================

    async def get_system_config(self) -> Optional[SystemConfig]:
        """获取系统配置 - 优先从数据库获取最新数据"""
        try:
            # 直接从数据库获取最新配置，避免缓存问题
            db = await self._get_db()
            config_collection = db.system_configs

            config_data = await config_collection.find_one(
                {"is_active": True},
                sort=[("version", -1)]
            )

            if config_data:
                print(f"📊 从数据库获取配置，版本: {config_data.get('version', 0)}, LLM配置数量: {len(config_data.get('llm_configs', []))}")
                # 补充必填字段默认值，防止旧版本文档缺失导致 ValidationError
                config_data.setdefault('config_name', config_data.get('config_name', 'bridged'))
                config_data.setdefault('config_type', config_data.get('config_type', 'system'))
                return SystemConfig(**config_data)

            # 如果没有配置，创建默认配置
            print("⚠️ 数据库中没有配置，创建默认配置")
            return await self._create_default_config()

        except Exception as e:
            print(f"❌ 从数据库获取配置失败: {e}")

            # 作为最后的回退，尝试从统一配置管理器获取
            try:
                unified_system_config = await unified_config.get_unified_system_config()
                if unified_system_config:
                    print("🔄 回退到统一配置管理器")
                    return unified_system_config
            except Exception as e2:
                print(f"从统一配置获取也失败: {e2}")

            return None

    async def _create_default_config(self) -> SystemConfig:
        """创建默认系统配置"""
        default_config = SystemConfig(
            config_name="默认配置",
            config_type="system",
            llm_configs=[
                LLMConfig(
                    provider=ModelProvider.OPENAI,
                    model_name="gpt-3.5-turbo",
                    api_key="your-openai-api-key",
                    api_base="https://api.openai.com/v1",
                    max_tokens=4000,
                    temperature=0.7,
                    enabled=False,
                    description="OpenAI GPT-3.5 Turbo模型"
                ),
                LLMConfig(
                    provider=ModelProvider.ZHIPU,
                    model_name="glm-4",
                    api_key="your-zhipu-api-key",
                    api_base="https://open.bigmodel.cn/api/paas/v4",
                    max_tokens=4000,
                    temperature=0.7,
                    enabled=True,
                    description="智谱AI GLM-4模型（推荐）"
                ),
                LLMConfig(
                    provider=ModelProvider.QWEN,
                    model_name="qwen-turbo",
                    api_key="your-qwen-api-key",
                    api_base="https://dashscope.aliyuncs.com/compatible-mode/v1",
                    max_tokens=4000,
                    temperature=0.7,
                    enabled=False,
                    description="阿里云通义千问模型"
                )
            ],
            default_llm="glm-4",
            data_source_configs=[
                DataSourceConfig(
                    name="AKShare",
                    type=DataSourceType.AKSHARE,
                    endpoint="https://akshare.akfamily.xyz",
                    timeout=30,
                    rate_limit=100,
                    enabled=True,
                    priority=1,
                    description="AKShare开源金融数据接口"
                ),
                DataSourceConfig(
                    name="Tushare",
                    type=DataSourceType.TUSHARE,
                    api_key="your-tushare-token",
                    endpoint="http://api.tushare.pro",
                    timeout=30,
                    rate_limit=200,
                    enabled=False,
                    priority=2,
                    description="Tushare专业金融数据接口"
                )
            ],
            default_data_source="AKShare",
            database_configs=[
                DatabaseConfig(
                    name="MongoDB主库",
                    type=DatabaseType.MONGODB,
                    host="localhost",
                    port=27017,
                    database="tradingagents",
                    enabled=True,
                    description="MongoDB主数据库"
                ),
                DatabaseConfig(
                    name="Redis缓存",
                    type=DatabaseType.REDIS,
                    host="localhost",
                    port=6379,
                    database="0",
                    enabled=True,
                    description="Redis缓存数据库"
                )
            ],
            system_settings={
                "max_concurrent_tasks": 3,
                "default_analysis_timeout": 300,
                "enable_cache": True,
                "cache_ttl": 3600,
                "log_level": "INFO",
                "enable_monitoring": True,
                # Worker/Queue intervals
                "worker_heartbeat_interval_seconds": 30,
                "queue_poll_interval_seconds": 1.0,
                "queue_cleanup_interval_seconds": 60.0,
                # SSE intervals
                "sse_poll_timeout_seconds": 1.0,
                "sse_heartbeat_interval_seconds": 10,
                "sse_task_max_idle_seconds": 300,
                "sse_batch_poll_interval_seconds": 2.0,
                "sse_batch_max_idle_seconds": 600,
                # TradingAgents runtime intervals (optional; DB-managed)
                "ta_hk_min_request_interval_seconds": 2.0,
                "ta_hk_timeout_seconds": 60,
                "ta_hk_max_retries": 3,
                "ta_hk_rate_limit_wait_seconds": 60,
                "ta_hk_cache_ttl_seconds": 86400,
                # 新增：TradingAgents 数据来源策略
                # 是否优先从 app 缓存(Mongo 集合 stock_basic_info / market_quotes) 读取
                "ta_use_app_cache": False,
                "ta_china_min_api_interval_seconds": 0.5,
                "ta_us_min_api_interval_seconds": 1.0,
                "ta_google_news_sleep_min_seconds": 2.0,
                "ta_google_news_sleep_max_seconds": 6.0,
                "app_timezone": "Asia/Shanghai"  # 默认时区，可通过运行时配置覆盖
            }
        )

        # 保存到数据库
        await self.save_system_config(default_config)
        return default_config

    async def save_system_config(self, config: SystemConfig) -> bool:
        """保存系统配置到数据库"""
        try:
            print(f"💾 开始保存配置，LLM配置数量: {len(config.llm_configs)}")

            # 保存到数据库
            db = await self._get_db()
            config_collection = db.system_configs

            # 更新时间戳和版本
            config.updated_at = now_tz()
            config.version += 1

            # 将当前激活的配置设为非激活
            update_result = await config_collection.update_many(
                {"is_active": True},
                {"$set": {"is_active": False}}
            )
            print(f"📝 禁用旧配置数量: {update_result.modified_count}")

            # 插入新配置 - 移除_id字段让MongoDB自动生成新的
            config_dict = config.model_dump(by_alias=True)
            if '_id' in config_dict:
                del config_dict['_id']  # 移除旧的_id，让MongoDB生成新的

            # 打印即将保存的 system_settings
            system_settings = config_dict.get('system_settings', {})
            print(f"📝 即将保存的 system_settings 包含 {len(system_settings)} 项")
            if 'quick_analysis_model' in system_settings:
                print(f"  ✓ 包含 quick_analysis_model: {system_settings['quick_analysis_model']}")
            else:
                print(f"  ⚠️  不包含 quick_analysis_model")
            if 'deep_analysis_model' in system_settings:
                print(f"  ✓ 包含 deep_analysis_model: {system_settings['deep_analysis_model']}")
            else:
                print(f"  ⚠️  不包含 deep_analysis_model")

            insert_result = await config_collection.insert_one(config_dict)
            print(f"📝 新配置ID: {insert_result.inserted_id}")

            # 验证保存结果
            saved_config = await config_collection.find_one({"_id": insert_result.inserted_id})
            if saved_config:
                print(f"✅ 配置保存成功，验证LLM配置数量: {len(saved_config.get('llm_configs', []))}")

                # 暂时跳过统一配置同步，避免冲突
                # unified_config.sync_to_legacy_format(config)

                return True
            else:
                print("❌ 配置保存验证失败")
                return False

        except Exception as e:
            print(f"❌ 保存配置失败: {e}")
            import traceback
            traceback.print_exc()
            return False

    async def set_default_data_source(self, data_source_name: str) -> bool:
        """设置默认数据源"""
        try:
            config = await self.get_system_config()
            if not config:
                return False

            # 检查指定的数据源是否存在
            source_exists = any(
                ds.name == data_source_name for ds in config.data_source_configs
            )

            if not source_exists:
                return False

            config.default_data_source = data_source_name
            return await self.save_system_config(config)

        except Exception as e:
            print(f"设置默认数据源失败: {e}")
            return False

    async def update_system_settings(self, settings: Dict[str, Any]) -> bool:
        """更新系统设置"""
        try:
            config = await self.get_system_config()
            if not config:
                return False

            # 打印更新前的系统设置
            print(f"📝 更新前 system_settings 包含 {len(config.system_settings)} 项")
            if 'quick_analysis_model' in config.system_settings:
                print(f"  ✓ 更新前包含 quick_analysis_model: {config.system_settings['quick_analysis_model']}")
            else:
                print(f"  ⚠️  更新前不包含 quick_analysis_model")

            # 更新系统设置
            config.system_settings.update(settings)

            # 打印更新后的系统设置
            print(f"📝 更新后 system_settings 包含 {len(config.system_settings)} 项")
            if 'quick_analysis_model' in config.system_settings:
                print(f"  ✓ 更新后包含 quick_analysis_model: {config.system_settings['quick_analysis_model']}")
            else:
                print(f"  ⚠️  更新后不包含 quick_analysis_model")
            if 'deep_analysis_model' in config.system_settings:
                print(f"  ✓ 更新后包含 deep_analysis_model: {config.system_settings['deep_analysis_model']}")
            else:
                print(f"  ⚠️  更新后不包含 deep_analysis_model")

            result = await self.save_system_config(config)

            # 同步到文件系统（供 unified_config 使用）
            if result:
                try:
                    from app.core.unified_config import unified_config
                    unified_config.sync_to_legacy_format(config)
                    print(f"✅ 系统设置已同步到文件系统")
                except Exception as e:
                    print(f"⚠️  同步系统设置到文件系统失败: {e}")

            return result

        except Exception as e:
            print(f"更新系统设置失败: {e}")
            return False

    async def get_system_settings(self) -> Dict[str, Any]:
        """获取系统设置"""
        try:
            config = await self.get_system_config()
            if not config:
                return {}
            return config.system_settings
        except Exception as e:
            print(f"获取系统设置失败: {e}")
            return {}

    # ==================== 配置导入导出 ====================

    async def export_config(self) -> Dict[str, Any]:
        """导出配置"""
        try:
            config = await self.get_system_config()
            if not config:
                return {}

            # 转换为可序列化的字典格式
            # 方案A：导出时对敏感字段脱敏/清空
            def _llm_sanitize(x: LLMConfig):
                d = x.model_dump()
                d["api_key"] = ""
                # 确保必填字段有默认值（防止导出 None 或空字符串）
                if not d.get("max_tokens") or d.get("max_tokens") == "":
                    d["max_tokens"] = 4000
                if not d.get("temperature") and d.get("temperature") != 0:
                    d["temperature"] = 0.7
                if not d.get("timeout") or d.get("timeout") == "":
                    d["timeout"] = 180
                if not d.get("retry_times") or d.get("retry_times") == "":
                    d["retry_times"] = 3
                return d
            def _ds_sanitize(x: DataSourceConfig):
                d = x.model_dump()
                d["api_key"] = ""
                d["api_secret"] = ""
                return d
            def _db_sanitize(x: DatabaseConfig):
                d = x.model_dump()
                d["password"] = ""
                return d
            export_data = {
                "config_name": config.config_name,
                "config_type": config.config_type,
                "llm_configs": [_llm_sanitize(llm) for llm in config.llm_configs],
                "default_llm": config.default_llm,
                "data_source_configs": [_ds_sanitize(ds) for ds in config.data_source_configs],
                "default_data_source": config.default_data_source,
                "database_configs": [_db_sanitize(db) for db in config.database_configs],
                # 方案A：导出时对 system_settings 中的敏感键做脱敏
                "system_settings": {k: (None if any(p in k.lower() for p in ("key","secret","password","token","client_secret")) else v) for k, v in (config.system_settings or {}).items()},
                "exported_at": now_tz().isoformat(),
                "version": config.version
            }

            return export_data

        except Exception as e:
            print(f"导出配置失败: {e}")
            return {}

    async def import_config(self, config_data: Dict[str, Any]) -> bool:
        """导入配置"""
        try:
            # 验证配置数据格式
            if not self._validate_config_data(config_data):
                return False

            # 创建新的系统配置（方案A：导入时忽略敏感字段）
            def _llm_sanitize_in(llm: Dict[str, Any]):
                d = dict(llm or {})
                d.pop("api_key", None)
                d["api_key"] = ""
                # 清理空字符串，让 Pydantic 使用默认值
                if d.get("max_tokens") == "" or d.get("max_tokens") is None:
                    d.pop("max_tokens", None)
                if d.get("temperature") == "" or d.get("temperature") is None:
                    d.pop("temperature", None)
                if d.get("timeout") == "" or d.get("timeout") is None:
                    d.pop("timeout", None)
                if d.get("retry_times") == "" or d.get("retry_times") is None:
                    d.pop("retry_times", None)
                return LLMConfig(**d)
            def _ds_sanitize_in(ds: Dict[str, Any]):
                d = dict(ds or {})
                d.pop("api_key", None)
                d.pop("api_secret", None)
                d["api_key"] = ""
                d["api_secret"] = ""
                return DataSourceConfig(**d)
            def _db_sanitize_in(db: Dict[str, Any]):
                d = dict(db or {})
                d.pop("password", None)
                d["password"] = ""
                return DatabaseConfig(**d)
            new_config = SystemConfig(
                config_name=config_data.get("config_name", "导入的配置"),
                config_type="imported",
                llm_configs=[_llm_sanitize_in(llm) for llm in config_data.get("llm_configs", [])],
                default_llm=config_data.get("default_llm"),
                data_source_configs=[_ds_sanitize_in(ds) for ds in config_data.get("data_source_configs", [])],
                default_data_source=config_data.get("default_data_source"),
                database_configs=[_db_sanitize_in(db) for db in config_data.get("database_configs", [])],
                system_settings=config_data.get("system_settings", {})
            )

            return await self.save_system_config(new_config)

        except Exception as e:
            print(f"导入配置失败: {e}")
            return False

    def _validate_config_data(self, config_data: Dict[str, Any]) -> bool:
        """验证配置数据格式"""
        try:
            required_fields = ["llm_configs", "data_source_configs", "database_configs", "system_settings"]
            for field in required_fields:
                if field not in config_data:
                    print(f"配置数据缺少必需字段: {field}")
                    return False

            return True

        except Exception as e:
            print(f"验证配置数据失败: {e}")
            return False

    async def migrate_legacy_config(self) -> bool:
        """迁移传统配置"""
        try:
            # 这里可以调用迁移脚本的逻辑
            # 或者直接在这里实现迁移逻辑
            from scripts.migrate_config_to_webapi import ConfigMigrator

            migrator = ConfigMigrator()
            return await migrator.migrate_all_configs()

        except Exception as e:
            print(f"迁移传统配置失败: {e}")
            return False
