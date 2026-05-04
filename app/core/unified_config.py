"""
统一配置管理系统 — 薄代理层

原 UnifiedConfigManager 已废弃。本模块保留类和实例签名，
内部委托到 app.services.config + settings.json 文件读取，
保持所有现有调用者不变。

Phase 4A 重构：移除直接文件系统操作，委托到 config_service。
"""

import json
import logging
import os
from pathlib import Path
from typing import Dict, List, Optional, Any

from app.models.config import (
    LLMConfig, DataSourceConfig, DatabaseConfig, SystemConfig,
    ModelProvider, DataSourceType, DatabaseType
)

logger = logging.getLogger(__name__)


class UnifiedConfigManager:
    """统一配置管理器 — 薄代理层"""

    def __init__(self):
        self._config_dir = Path("config")
        self._models_file = self._config_dir / "models.json"
        self._settings_file = self._config_dir / "settings.json"

    # ── 内部辅助 ──────────────────────────────────────────────────────

    def _load_json(self, path: Path) -> Dict[str, Any]:
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return {}

    def _save_json(self, path: Path, data: Any):
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    # ── 模型配置 ──────────────────────────────────────────────────────

    def get_legacy_models(self) -> List[Dict[str, Any]]:
        return self._load_json(self._models_file)

    def get_llm_configs(self) -> List[LLMConfig]:
        """获取标准化的 LLM 配置列表（从 models.json 读取）"""
        legacy = self.get_legacy_models()
        result = []
        for m in legacy:
            try:
                cfg = LLMConfig(
                    provider=m.get("provider", "openai"),
                    model_name=m.get("model_name", ""),
                    api_key="",
                    api_base=m.get("base_url"),
                    max_tokens=m.get("max_tokens", 4000),
                    temperature=m.get("temperature", 0.7),
                    enabled=m.get("enabled", True),
                    description=f"{m.get('provider', '')} {m.get('model_name', '')}",
                )
                result.append(cfg)
            except Exception as e:
                logger.warning(f"转换模型配置失败: {m}, 错误: {e}")
        return result

    def save_llm_config(self, llm_config: LLMConfig) -> bool:
        """保存 LLM 配置到 models.json"""
        try:
            models = self.get_legacy_models()
            entry = {
                "provider": llm_config.provider,
                "model_name": llm_config.model_name,
                "api_key": "",
                "base_url": llm_config.api_base,
                "max_tokens": llm_config.max_tokens,
                "temperature": llm_config.temperature,
                "enabled": llm_config.enabled,
            }
            updated = False
            for i, m in enumerate(models):
                if m.get("provider") == entry["provider"] and m.get("model_name") == entry["model_name"]:
                    models[i] = entry
                    updated = True
                    break
            if not updated:
                models.append(entry)
            self._save_json(self._models_file, models)
            return True
        except Exception as e:
            logger.error(f"保存 LLM 配置失败: {e}")
            return False

    # ── 系统设置 ──────────────────────────────────────────────────────

    def get_system_settings(self) -> Dict[str, Any]:
        return self._load_json(self._settings_file)

    def save_system_settings(self, settings: Dict[str, Any]) -> bool:
        """保存系统设置（合并后写入）"""
        try:
            current = self.get_system_settings()
            merged = current.copy()
            merged.update(settings)
            if "mcp_tool_loader" in merged:
                merged["mcp_tool_loader"] = None
            self._save_json(self._settings_file, merged)
            return True
        except Exception as e:
            logger.error(f"保存系统设置失败: {e}")
            return False

    def get_default_model(self) -> str:
        settings = self.get_system_settings()
        return settings.get("quick_analysis_model", settings.get("default_model", "qwen-turbo"))

    def get_quick_analysis_model(self) -> str:
        settings = self.get_system_settings()
        return settings.get("quick_analysis_model") or settings.get("quick_think_llm", "qwen-turbo")

    def get_deep_analysis_model(self) -> str:
        settings = self.get_system_settings()
        return settings.get("deep_analysis_model") or settings.get("deep_think_llm", "qwen-max")

    # ── 数据源配置 ──────────────────────────────────────────────────────

    def _normalize_data_source_config(self, ds_config: Dict[str, Any]) -> Dict[str, Any]:
        normalized = dict(ds_config or {})
        raw_type = normalized.get("type")
        raw_name = normalized.get("name")
        if not raw_type:
            inferred_name = str(raw_name or "").strip().lower()
            if "tushare" in inferred_name:
                raw_type = DataSourceType.TUSHARE.value
            elif "finnhub" in inferred_name:
                raw_type = DataSourceType.FINNHUB.value
            else:
                raw_type = DataSourceType.AKSHARE.value
        if not raw_name:
            raw_name = str(raw_type).strip() or DataSourceType.AKSHARE.value
        normalized["type"] = raw_type
        normalized["name"] = raw_name
        return normalized

    def get_data_source_configs(self) -> List[DataSourceConfig]:
        """获取数据源配置（同步版本）— 优先从数据库读取"""
        try:
            from app.core.database import get_mongo_db_sync
            db = get_mongo_db_sync()
            config_data = db.system_configs.find_one(
                {"is_active": True}, sort=[("version", -1)]
            )
            if config_data and config_data.get("data_source_configs"):
                result = []
                for ds in config_data["data_source_configs"]:
                    try:
                        normalized = self._normalize_data_source_config(ds)
                        result.append(DataSourceConfig(**normalized))
                    except Exception:
                        continue
                result.sort(key=lambda x: x.priority, reverse=True)
                return result
        except Exception:
            pass
        # 回退到硬编码
        return [
            DataSourceConfig(
                name="AKShare", type=DataSourceType.AKSHARE,
                endpoint="https://akshare.akfamily.xyz",
                enabled=True, priority=1,
                description="AKShare开源金融数据接口",
            ),
        ]

    async def get_data_source_configs_async(self) -> List[DataSourceConfig]:
        """获取数据源配置（异步版本）— 优先从数据库读取"""
        try:
            from app.core.database import get_mongo_db
            db = get_mongo_db()
            config_data = await db.system_configs.find_one(
                {"is_active": True}, sort=[("version", -1)]
            )
            if config_data and config_data.get("data_source_configs"):
                result = []
                for ds in config_data["data_source_configs"]:
                    try:
                        normalized = self._normalize_data_source_config(ds)
                        result.append(DataSourceConfig(**normalized))
                    except Exception:
                        continue
                result.sort(key=lambda x: x.priority, reverse=True)
                return result
        except Exception:
            pass
        return [
            DataSourceConfig(
                name="AKShare", type=DataSourceType.AKSHARE,
                endpoint="https://akshare.akfamily.xyz",
                enabled=True, priority=1,
                description="AKShare开源金融数据接口",
            ),
        ]

    # ── 数据库配置 ──────────────────────────────────────────────────────

    def get_database_configs(self) -> List[DatabaseConfig]:
        return [
            DatabaseConfig(
                name="MongoDB主库", type=DatabaseType.MONGODB,
                host=os.getenv("MONGODB_HOST", "localhost"),
                port=int(os.getenv("MONGODB_PORT", "27017")),
                database=os.getenv("MONGODB_DATABASE", "tradingagents"),
                enabled=True, description="MongoDB主数据库",
            ),
            DatabaseConfig(
                name="Redis缓存", type=DatabaseType.REDIS,
                host=os.getenv("REDIS_HOST", "localhost"),
                port=int(os.getenv("REDIS_PORT", "6379")),
                database=os.getenv("REDIS_DB", "0"),
                enabled=True, description="Redis缓存数据库",
            ),
        ]

    # ── 统一配置接口 ──────────────────────────────────────────────────

    async def get_unified_system_config(self) -> SystemConfig:
        try:
            return SystemConfig(
                config_name="统一系统配置",
                config_type="unified",
                llm_configs=self.get_llm_configs(),
                default_llm=self.get_default_model(),
                data_source_configs=self.get_data_source_configs(),
                default_data_source="AKShare",
                database_configs=self.get_database_configs(),
                system_settings=self.get_system_settings(),
            )
        except Exception as e:
            logger.error(f"获取统一配置失败: {e}")
            return SystemConfig(
                config_name="默认配置", config_type="default",
                llm_configs=[], data_source_configs=[], database_configs=[],
                system_settings={},
            )

    def sync_to_legacy_format(self, system_config: SystemConfig) -> bool:
        """同步配置到传统格式（写入 settings.json）"""
        try:
            current = self.get_system_settings()
            ss = system_config.system_settings or {}
            if "quick_analysis_model" in ss:
                current["quick_think_llm"] = ss["quick_analysis_model"]
                current["quick_analysis_model"] = ss["quick_analysis_model"]
            if "deep_analysis_model" in ss:
                current["deep_think_llm"] = ss["deep_analysis_model"]
                current["deep_analysis_model"] = ss["deep_analysis_model"]
            if system_config.default_llm:
                current["default_model"] = system_config.default_llm
            self.save_system_settings(current)
            return True
        except Exception as e:
            logger.error(f"同步配置到传统格式失败: {e}")
            return False


# 全局实例
unified_config = UnifiedConfigManager()
