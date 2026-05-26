"""
系统配置与导入导出管理服务
"""

import json
import logging
from pathlib import Path
from typing import List, Optional, Dict, Any

import yaml

from app.core.database import get_mongo_db
from app.models.config import (
    SystemConfig, LLMConfig, DataSourceConfig, DatabaseConfig,
    ModelProvider, DataSourceType, DatabaseType
)
from app.constants.llm_defaults import (
    DEFAULT_MAX_TOKENS,
    DEFAULT_TEMPERATURE,
    DEFAULT_LLM_FIELD_FALLBACKS,
)
from app.utils.timezone import now_tz

logger = logging.getLogger(__name__)

EXPORT_VERSION = "2.0"

SENSITIVE_KEY_PATTERS = ("key", "secret", "password", "token", "client_secret")

# 需要导出的独立 MongoDB 配置集合
EXPORTABLE_COLLECTIONS = [
    "llm_providers",
    "model_catalog",
    "market_categories",
    "datasource_groupings",
    "platform_configs",
]

# Agent 配置阶段与文件名映射
AGENT_PHASE_FILES = {
    1: "phase1_agents_config.yaml",
    2: "phase2_agents_config.yaml",
    3: "phase3_agents_config.yaml",
}


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
                    enabled=False,
                    description="OpenAI GPT-3.5 Turbo模型"
                ),
                LLMConfig(
                    provider=ModelProvider.ZHIPU,
                    model_name="glm-4",
                    api_key="your-zhipu-api-key",
                    api_base="https://open.bigmodel.cn/api/paas/v4",
                    enabled=True,
                    description="智谱AI GLM-4模型（推荐）"
                ),
                LLMConfig(
                    provider=ModelProvider.QWEN,
                    model_name="qwen-turbo",
                    api_key="your-qwen-api-key",
                    api_base="https://dashscope.aliyuncs.com/compatible-mode/v1",
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
        """保存系统配置到数据库（原子操作）"""
        try:
            logger.info(f"保存配置，LLM配置数量: {len(config.llm_configs)}")

            db = await self._get_db()
            config_collection = db.system_configs

            config.updated_at = now_tz()
            config.version += 1

            config_dict = config.model_dump(by_alias=True)
            if '_id' in config_dict:
                del config_dict['_id']
            config_dict['is_active'] = True

            # 尝试使用事务保证原子性
            try:
                async with await db.client.start_session() as session:
                    async with session.start_transaction():
                        await config_collection.update_many(
                            {"is_active": True},
                            {"$set": {"is_active": False}},
                            session=session,
                        )
                        insert_result = await config_collection.insert_one(
                            config_dict, session=session
                        )
                logger.info(f"配置保存成功（事务模式），ID: {insert_result.inserted_id}")
                return True
            except Exception as txn_err:
                # fallback：先插入新配置，再标记旧配置
                logger.debug(f"事务不可用，使用 fallback: {txn_err}")
                insert_result = await config_collection.insert_one(config_dict)
                await config_collection.update_many(
                    {"is_active": True, "_id": {"$ne": insert_result.inserted_id}},
                    {"$set": {"is_active": False}},
                )
                logger.info(f"配置保存成功（fallback模式），ID: {insert_result.inserted_id}")
                return True

        except Exception as e:
            logger.error("保存系统配置失败: %s", e, exc_info=True)
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
            if 'analyst_model' in config.system_settings:
                print(f"  ✓ 更新前包含 analyst_model: {config.system_settings['analyst_model']}")
            else:
                print("  ⚠️  更新前不包含 analyst_model")

            # 更新系统设置
            config.system_settings.update(settings)

            # 打印更新后的系统设置
            print(f"📝 更新后 system_settings 包含 {len(config.system_settings)} 项")
            if 'analyst_model' in config.system_settings:
                print(f"  ✓ 更新后包含 analyst_model: {config.system_settings['analyst_model']}")
            else:
                print("  ⚠️  更新后不包含 analyst_model")
            if 'debate_model' in config.system_settings:
                print(f"  ✓ 更新后包含 debate_model: {config.system_settings['debate_model']}")
            else:
                print("  ⚠️  更新后不包含 debate_model")

            result = await self.save_system_config(config)

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

    # ---------- 辅助方法 ----------

    @staticmethod
    def _sanitize_dict(d: Dict[str, Any], sensitive_keys: List[str]) -> Dict[str, Any]:
        """将指定敏感键的值清空"""
        out = dict(d)
        for key in sensitive_keys:
            if key in out:
                out[key] = ""
        return out

    @staticmethod
    def _sanitize_settings(settings: Dict[str, Any]) -> Dict[str, Any]:
        """脱敏 system_settings 中的敏感键"""
        return {
            k: (None if any(p in k.lower() for p in SENSITIVE_KEY_PATTERS) else v)
            for k, v in settings.items()
        }

    @staticmethod
    def _get_agent_config_dir() -> Path:
        """获取 Agent 配置文件目录"""
        from app.core.env import get_env
        env_dir = get_env("AGENT_CONFIG_DIR")
        if env_dir:
            path = Path(env_dir)
            if path.exists():
                return path
        project_root = Path(__file__).resolve().parents[3]
        return project_root / "config" / "agents"

    def _read_agent_yaml(self, phase: int) -> Optional[Dict[str, Any]]:
        """读取指定阶段的 Agent YAML 配置"""
        filename = AGENT_PHASE_FILES.get(phase)
        if not filename:
            return None
        config_path = self._get_agent_config_dir() / filename
        if not config_path.exists():
            logger.warning(f"Agent 配置文件不存在: {config_path}")
            return None
        try:
            with config_path.open("r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            return data
        except Exception as e:
            logger.error(f"读取 Agent 配置失败 [{config_path}]: {e}")
            return None

    def _write_agent_yaml(self, phase: int, data: Dict[str, Any]) -> bool:
        """写入指定阶段的 Agent YAML 配置"""
        filename = AGENT_PHASE_FILES.get(phase)
        if not filename:
            return False
        config_path = self._get_agent_config_dir() / filename
        try:
            config_path.parent.mkdir(parents=True, exist_ok=True)
            tmp_path = config_path.with_suffix(".tmp")
            with tmp_path.open("w", encoding="utf-8") as f:
                yaml.safe_dump(data, f, allow_unicode=True, sort_keys=False, default_flow_style=False)
            tmp_path.replace(config_path)
            logger.info(f"Agent 配置已写入: {config_path}")
            return True
        except Exception as e:
            logger.error(f"写入 Agent 配置失败 [{config_path}]: {e}")
            return False

    # ---------- 导出 ----------

    async def export_config(self) -> Dict[str, Any]:
        """导出全部配置（v2.0 格式，覆盖所有集合 + Agent YAML）"""
        try:
            db = await self._get_db()

            # 1. 导出 system_configs（核心配置）
            config = await self.get_system_config()
            system_configs_data = {}
            if config:
                def _llm_sanitize(x: LLMConfig):
                    d = self._sanitize_dict(x.model_dump(), ["api_key"])
                    for fld in ("max_tokens", "timeout", "retry_times"):
                        if not d.get(fld) or d.get(fld) == "":
                            d[fld] = DEFAULT_LLM_FIELD_FALLBACKS[fld]
                    if not d.get("temperature") and d.get("temperature") != 0:
                        d["temperature"] = DEFAULT_TEMPERATURE
                    return d

                system_configs_data = {
                    "config_name": config.config_name,
                    "config_type": config.config_type,
                    "llm_configs": [_llm_sanitize(llm) for llm in config.llm_configs],
                    "default_llm": config.default_llm,
                    "data_source_configs": [
                        self._sanitize_dict(ds.model_dump(), ["api_key", "api_secret"])
                        for ds in config.data_source_configs
                    ],
                    "default_data_source": config.default_data_source,
                    "database_configs": [
                        self._sanitize_dict(db_item.model_dump(), ["password"])
                        for db_item in config.database_configs
                    ],
                    "system_settings": self._sanitize_settings(config.system_settings or {}),
                    "version": config.version,
                }

            # 2. 导出独立集合
            extra_collections: Dict[str, Any] = {}
            for col_name in EXPORTABLE_COLLECTIONS:
                try:
                    docs = await db[col_name].find().to_list(1000)
                    # 脱敏：遍历文档中的敏感键
                    sanitized_docs = []
                    for doc in docs:
                        doc.pop("_id", None)
                        clean = {}
                        for k, v in doc.items():
                            if any(p in k.lower() for p in SENSITIVE_KEY_PATTERS):
                                clean[k] = None
                            else:
                                clean[k] = v
                        sanitized_docs.append(clean)
                    extra_collections[col_name] = sanitized_docs
                except Exception as e:
                    logger.warning(f"导出集合 {col_name} 失败: {e}")
                    extra_collections[col_name] = []

            # 3. 导出 Agent YAML 配置
            agent_configs: Dict[str, Any] = {}
            for phase in AGENT_PHASE_FILES:
                data = self._read_agent_yaml(phase)
                if data:
                    agent_configs[f"phase{phase}"] = data

            # 4. 组装导出数据
            export_data: Dict[str, Any] = {
                "export_version": EXPORT_VERSION,
                "exported_at": now_tz().isoformat(),
                "system_configs": system_configs_data,
                **extra_collections,
                "agent_configs": agent_configs,
            }

            logger.info(
                f"配置导出完成: system_configs={bool(system_configs_data)}, "
                f"额外集合=[{', '.join(f'{k}={len(v)}' for k, v in extra_collections.items() if isinstance(v, list))}], "
                f"agent_configs 阶段=[{', '.join(agent_configs.keys())}]"
            )
            return export_data

        except Exception as e:
            logger.error(f"导出配置失败: {e}", exc_info=True)
            return {}

    # ---------- 导入 ----------

    async def import_config(self, config_data: Dict[str, Any]) -> bool:
        """导入全部配置（兼容 v1.0 旧格式和 v2.0 新格式）"""
        try:
            if not self._validate_config_data(config_data):
                return False

            db = await self._get_db()
            is_v2 = config_data.get("export_version") == EXPORT_VERSION

            # ---- 1. 导入 system_configs ----
            sc_data = config_data.get("system_configs", config_data) if is_v2 else config_data
            system_ok = await self._import_system_configs(db, sc_data)

            # ---- 2. 导入独立集合（仅 v2.0） ----
            collections_ok = True
            if is_v2:
                for col_name in EXPORTABLE_COLLECTIONS:
                    docs = config_data.get(col_name, [])
                    if docs:
                        try:
                            await db[col_name].delete_many({})
                            await db[col_name].insert_many(docs)
                            logger.info(f"导入集合 {col_name}: {len(docs)} 条")
                        except Exception as e:
                            logger.warning(f"导入集合 {col_name} 失败: {e}")
                            collections_ok = False

            # ---- 3. 导入 Agent YAML 配置（仅 v2.0） ----
            agent_ok = True
            if is_v2:
                agent_data = config_data.get("agent_configs", {})
                for phase_str, phase_data in agent_data.items():
                    try:
                        phase_num = int(phase_str.replace("phase", ""))
                        if not self._write_agent_yaml(phase_num, phase_data):
                            agent_ok = False
                    except (ValueError, KeyError) as e:
                        logger.warning(f"导入 Agent 配置 phase={phase_str} 失败: {e}")

            # ---- 4. 刷新缓存与桥接 ----
            await self._post_import_reload()

            overall = system_ok and collections_ok and agent_ok
            logger.info(f"配置导入完成: system={system_ok}, collections={collections_ok}, agent={agent_ok}")
            return overall

        except Exception as e:
            logger.error(f"导入配置失败: {e}", exc_info=True)
            return False

    async def _import_system_configs(self, db, sc_data: Dict[str, Any]) -> bool:
        """将 system_configs 部分写入数据库"""
        def _llm_sanitize_in(llm: Dict[str, Any]):
            d = dict(llm or {})
            d["api_key"] = ""
            for fld in ("max_tokens", "temperature", "timeout", "retry_times"):
                if d.get(fld) == "" or d.get(fld) is None:
                    d.pop(fld, None)
            return LLMConfig(**d)

        def _ds_sanitize_in(ds: Dict[str, Any]):
            d = dict(ds or {})
            d["api_key"] = ""
            d["api_secret"] = ""
            return DataSourceConfig(**d)

        def _db_sanitize_in(db_cfg: Dict[str, Any]):
            d = dict(db_cfg or {})
            d["password"] = ""
            return DatabaseConfig(**d)

        new_config = SystemConfig(
            config_name=sc_data.get("config_name", "导入的配置"),
            config_type="imported",
            llm_configs=[_llm_sanitize_in(llm) for llm in sc_data.get("llm_configs", [])],
            default_llm=sc_data.get("default_llm"),
            data_source_configs=[_ds_sanitize_in(ds) for ds in sc_data.get("data_source_configs", [])],
            default_data_source=sc_data.get("default_data_source"),
            database_configs=[_db_sanitize_in(db_cfg) for db_cfg in sc_data.get("database_configs", [])],
            system_settings=sc_data.get("system_settings", {}),
        )
        return await self.save_system_config(new_config)

    async def _post_import_reload(self):
        """导入后刷新缓存、桥接环境变量、清除智能体缓存"""
        # 1. 刷新 ConfigProvider 缓存
        try:
            from app.services.config_provider import provider as config_provider
            config_provider.invalidate()
            logger.info("已刷新 ConfigProvider 缓存")
        except Exception as e:
            logger.warning(f"刷新 ConfigProvider 缓存失败: {e}")

        # 2. 重新桥接环境变量
        try:
            from app.core.config_bridge import reload_bridged_config
            await reload_bridged_config()
            logger.info("已重新桥接环境变量")
        except Exception as e:
            logger.warning(f"重新桥接环境变量失败: {e}")

        # 3. 清除智能体配置缓存
        try:
            from app.engine.agents.analysts.dynamic_analyst import DynamicAnalystFactory
            DynamicAnalystFactory.clear_cache()
            logger.info("已清除 DynamicAnalystFactory 缓存")
        except ImportError:
            pass
        except Exception as e:
            logger.warning(f"清除智能体缓存失败: {e}")

    # ---------- 校验 ----------

    def _validate_config_data(self, config_data: Dict[str, Any]) -> bool:
        """验证配置数据格式（兼容 v1.0 和 v2.0）"""
        try:
            version = config_data.get("export_version")

            if version == EXPORT_VERSION:
                # v2.0 格式：system_configs 为必填
                sc = config_data.get("system_configs", {})
                if not sc and not config_data.get("llm_configs"):
                    print("配置数据缺少 system_configs 或 llm_configs")
                    return False
                return True

            # v1.0 格式（向后兼容）：检查原始 4 个必需字段
            required_fields = ["llm_configs", "data_source_configs", "database_configs", "system_settings"]
            for field in required_fields:
                if field not in config_data:
                    print(f"配置数据缺少必需字段: {field}")
                    return False
            return True

        except Exception as e:
            print(f"验证配置数据失败: {e}")
            return False

    # ---------- 传统配置迁移 ----------

    async def migrate_legacy_config(self) -> bool:
        """从 YAML/JSON 文件迁移配置到数据库（内联实现，不依赖外部脚本）"""
        try:
            project_root = Path(__file__).resolve().parents[3]
            migrated_items: List[str] = []

            # 1. 迁移 config/agents/*.yaml → 确认文件存在（YAML 本身就是 Agent 的真相来源）
            agents_dir = project_root / "config" / "agents"
            if agents_dir.exists():
                phase_count = 0
                for phase in AGENT_PHASE_FILES:
                    yaml_path = agents_dir / AGENT_PHASE_FILES[phase]
                    if yaml_path.exists():
                        phase_count += 1
                if phase_count:
                    migrated_items.append(f"agent YAML 已就绪 ({phase_count} 个阶段)")

            # 2. 刷新
            await self._post_import_reload()

            if migrated_items:
                logger.info(f"传统配置迁移完成: {', '.join(migrated_items)}")
            else:
                logger.info("未发现可迁移的传统配置文件")
            return True

        except Exception as e:
            logger.error(f"迁移传统配置失败: {e}", exc_info=True)
            return False
