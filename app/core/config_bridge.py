"""
配置桥接模块
将数据库中的配置桥接到环境变量，供引擎层和 TradingAgents 核心库使用。

Phase 4D 简化说明：
- 移除了 Step 5（_bridge_system_settings 写回 config/settings.json，文件已废弃）
- 移除了 Step 6（重初始化 config_manager.mongodb_storage，config_manager 已标记 deprecated）
- 移除了 Step 7（_sync_pricing_config_from_db 后台任务，定价由 config_service 管理）
- 保留核心引导逻辑：MongoDB 环境变量、LLM Provider API Key、模型配置、数据源 API Key
"""

import json
import os
import logging
from pathlib import Path
from typing import Optional

from app.core.database import get_mongo_db

logger = logging.getLogger("app.config_bridge")


async def bridge_config_to_env() -> bool:
    """
    将数据库配置桥接到环境变量，供引擎层通过 os.getenv() 读取。

    核心步骤：
    1. 桥接 MongoDB 存储环境变量
    2. 从 llm_providers 集合桥接厂家 API Key → {PROVIDER}_API_KEY
    3. 桥接默认/快速/深度分析模型 → TRADINGAGENTS_*_MODEL
    4. 桥接数据源 API Key（Tushare Token、FinnHub Key）
    """
    try:
        logger.info("开始桥接配置到环境变量...")
        bridged_count = 0

        # ── Step 1：MongoDB 存储环境变量 ──────────────────────────────
        use_mongodb_storage = os.getenv("USE_MONGODB_STORAGE", "true")
        os.environ["USE_MONGODB_STORAGE"] = use_mongodb_storage
        logger.info(f"  USE_MONGODB_STORAGE={use_mongodb_storage}")
        bridged_count += 1

        mongodb_conn_str = os.getenv("MONGODB_CONNECTION_STRING")
        if mongodb_conn_str:
            os.environ["MONGODB_CONNECTION_STRING"] = mongodb_conn_str
            logger.info(f"  MONGODB_CONNECTION_STRING (length={len(mongodb_conn_str)})")
            bridged_count += 1

        mongodb_db_name = os.getenv("MONGODB_DATABASE_NAME", "tradingagents")
        os.environ["MONGODB_DATABASE_NAME"] = mongodb_db_name
        logger.info(f"  MONGODB_DATABASE_NAME={mongodb_db_name}")
        bridged_count += 1

        # ── Step 2：从 llm_providers 集合桥接 API Key ──────────────────
        try:
            from app.models.config import LLMProvider

            db = get_mongo_db()
            providers_data = await db.llm_providers.find().to_list(None)
            providers = [LLMProvider(**d) for d in providers_data]
            logger.info(f"  从数据库读取到 {len(providers)} 个厂家配置")

            for provider in providers:
                if not provider.is_active:
                    continue
                env_key = f"{provider.name.upper()}_API_KEY"
                existing = os.getenv(env_key)
                # .env 文件 > 数据库（仅当环境变量不存在或为占位符时才桥接）
                if existing and not existing.startswith("your_"):
                    logger.debug(f"  {env_key}: 使用 .env 值")
                    bridged_count += 1
                elif provider.api_key and not provider.api_key.startswith("your_"):
                    os.environ[env_key] = provider.api_key
                    logger.debug(f"  {env_key}: 使用数据库值 (length={len(provider.api_key)})")
                    bridged_count += 1
        except Exception as e:
            logger.error(f"从数据库读取厂家配置失败: {e}", exc_info=True)

        # ── Step 3 & 4：桥接模型配置 + 数据源 API Key ─────────────────
        try:
            from app.services.config_service import config_service

            system_config = await config_service.get_system_config()
            if system_config:
                # 默认模型
                if system_config.default_llm:
                    os.environ["TRADINGAGENTS_DEFAULT_MODEL"] = system_config.default_llm
                    logger.info(f"  TRADINGAGENTS_DEFAULT_MODEL={system_config.default_llm}")
                    bridged_count += 1

                # 快速/深度分析模型（从 system_settings 读取）
                ss = system_config.system_settings or {}
                for model_key, env_name in [
                    ("quick_analysis_model", "TRADINGAGENTS_QUICK_MODEL"),
                    ("deep_analysis_model", "TRADINGAGENTS_DEEP_MODEL"),
                ]:
                    val = ss.get(model_key)
                    if val:
                        os.environ[env_name] = val
                        logger.info(f"  {env_name}={val}")
                        bridged_count += 1

                # 数据源 API Key
                ds_env_map = {"tushare": "TUSHARE_TOKEN", "finnhub": "FINNHUB_API_KEY"}
                for ds_config in system_config.data_source_configs:
                    if not ds_config.enabled or not ds_config.api_key:
                        continue
                    if ds_config.api_key.startswith("your_"):
                        continue
                    env_key = ds_env_map.get(ds_config.type.value)
                    if env_key:
                        os.environ[env_key] = ds_config.api_key
                        logger.debug(f"  {env_key}: 使用数据库值")
                        bridged_count += 1
            else:
                logger.warning("  未找到激活的系统配置，模型和数据源将使用 .env 降级方案")
        except Exception as e:
            logger.error(f"桥接系统配置失败: {e}", exc_info=True)

        logger.info(f"配置桥接完成，共桥接 {bridged_count} 项配置")
        return True
    except Exception as e:
        logger.error(f"配置桥接失败: {e}", exc_info=True)
        logger.warning("TradingAgents 将使用 .env 文件中的配置")
        return False


# ── 公共查询接口 ──────────────────────────────────────────────────────

def get_bridged_api_key(provider: str) -> Optional[str]:
    """获取桥接的 API 密钥"""
    return os.environ.get(f"{provider.upper()}_API_KEY")


def get_bridged_model(model_type: str = "default") -> Optional[str]:
    """获取桥接的模型名称（default / quick / deep）"""
    key = {"quick": "TRADINGAGENTS_QUICK_MODEL", "deep": "TRADINGAGENTS_DEEP_MODEL"}.get(
        model_type, "TRADINGAGENTS_DEFAULT_MODEL"
    )
    return os.environ.get(key)


def clear_bridged_config():
    """清除桥接的环境变量（用于测试或重新加载）"""
    keys_to_clear = [
        "TRADINGAGENTS_DEFAULT_MODEL", "TRADINGAGENTS_QUICK_MODEL",
        "TRADINGAGENTS_DEEP_MODEL", "TUSHARE_TOKEN", "FINNHUB_API_KEY",
        "APP_TIMEZONE", "CURRENCY_PREFERENCE",
    ]
    for p in ("OPENAI", "ANTHROPIC", "GOOGLE", "DEEPSEEK", "DASHSCOPE",
              "QIANFAN", "ZHIPU", "SILICONFLOW", "OPENROUTER"):
        keys_to_clear.append(f"{p}_API_KEY")
    for key in keys_to_clear:
        os.environ.pop(key, None)
    logger.info("已清除所有桥接的配置")


async def reload_bridged_config():
    """重新加载桥接配置（配置更新后调用）"""
    logger.info("重新加载配置桥接...")
    clear_bridged_config()
    return await bridge_config_to_env()


# ── 定价配置同步（供 llm.py 路由调用）──────────────────────────────────
# Phase 4D 注：此功能原为 Step 7 后台任务，现保留为 async 函数供路由主动调用。
# config/pricing.json 仅用于引擎层 cost tracking，从 SystemConfig.llm_configs 生成。

async def sync_pricing_config_now() -> bool:
    """将定价配置写入 config/pricing.json。返回 True 表示成功。"""
    try:
        from app.services.config_service import config_service
        system_config = await config_service.get_system_config()
        if not system_config:
            logger.warning("sync_pricing_config_now: 未找到系统配置")
            return False

        pricing_configs = []
        for cfg in system_config.llm_configs:
            if cfg.enabled:
                pricing_configs.append({
                    "provider": cfg.provider.value if hasattr(cfg.provider, "value") else str(cfg.provider),
                    "model_name": cfg.model_name,
                    "input_price_per_1k": cfg.input_price_per_1k or 0.0,
                    "output_price_per_1k": cfg.output_price_per_1k or 0.0,
                    "currency": cfg.currency or "CNY",
                })

        config_dir = Path(__file__).parent.parent.parent / "config"
        config_dir.mkdir(exist_ok=True)
        pricing_file = config_dir / "pricing.json"
        with open(pricing_file, "w", encoding="utf-8") as f:
            json.dump(pricing_configs, f, ensure_ascii=False, indent=2)

        logger.info(f"定价配置已写入 {pricing_file}: {len(pricing_configs)} 个模型")
        return True
    except Exception as e:
        logger.error(f"sync_pricing_config_now 失败: {e}", exc_info=True)
        return False


__all__ = [
    "bridge_config_to_env",
    "get_bridged_api_key",
    "get_bridged_model",
    "clear_bridged_config",
    "reload_bridged_config",
    "sync_pricing_config_now",
]
