"""LLM 模型配置与 provider 解析（自 analysis_service.py 拆分）。

职责：模型名 → provider/backend_url 解析（异步/同步，元数据缓存）、
API Key 实时解析（不缓存明文）、硬编码默认映射兜底、分析配置组装
（create_analysis_config）。
"""
# data-access-exempt: 应用层集合（system_configs/llm_providers）直查属架构豁免（与原 analysis_service 同口径）

import logging
from typing import Optional

from app.core.database import get_mongo_db_sync
from app.core.lru_cache import BoundedLRUCache
from app.engine.default_config import DEFAULT_CONFIG
from app.services.config_service import config_service

logger = logging.getLogger(__name__)



async def get_provider_by_model_name(model_name: str) -> str:
    """
    根据模型名称从数据库配置中查找对应的供应商（异步版本）
    """
    try:
        # 从配置服务获取系统配置
        system_config = await config_service.get_system_config()
        if not system_config or not system_config.llm_configs:
            logger.warning("⚠️ 系统配置为空，使用默认供应商映射")
            return _get_default_provider_by_model(model_name)

        # 在LLM配置中查找匹配的模型
        for llm_config in system_config.llm_configs:
            if llm_config.model_name == model_name:
                provider = (
                    llm_config.provider.value if hasattr(llm_config.provider, "value") else str(llm_config.provider)
                )
                logger.info(f"✅ 从数据库找到模型 {model_name} 的供应商: {provider}")
                return provider

        # 如果数据库中没有找到，使用默认映射
        logger.warning(f"⚠️ 数据库中未找到模型 {model_name}，使用默认映射")
        return _get_default_provider_by_model(model_name)

    except Exception as e:
        logger.error(f"❌ 查找模型供应商失败: {e}", exc_info=True)
        return _get_default_provider_by_model(model_name)


def get_provider_by_model_name_sync(model_name: str) -> str:
    """
    根据模型名称从数据库配置中查找对应的供应商（同步版本）
    """
    provider_info = get_provider_and_url_by_model_sync(model_name)
    return provider_info["provider"]


# 模型能力元数据缓存（仅缓存 provider + backend_url，绝不缓存明文 API Key）。
# API Key 通过独立路径 _resolve_api_key_sync() 实时从 DB 读取，避免明文密钥长期驻留内存。
_model_metadata_cache: BoundedLRUCache = BoundedLRUCache(maxsize=32, ttl=300, name="model_metadata_cache")
_MODEL_API_KEY_PLACEHOLDER = "__resolved_at_runtime__"


def _resolve_api_key_sync(db, provider: str, model_api_key: Optional[str]) -> Optional[str]:
    """实时从 MongoDB 解析 API Key（模型配置优先，厂家配置兜底）。

    返回明文 API Key 或 None。不缓存——密钥每次调用都从 DB 实时读取。
    """
    if model_api_key and model_api_key.strip() and model_api_key != "your-api-key":
        return model_api_key.strip()
    provider_doc = db.llm_providers.find_one({"name": provider})
    if provider_doc and provider_doc.get("api_key"):
        provider_api_key = provider_doc["api_key"]
        if provider_api_key and provider_api_key.strip() and provider_api_key != "your-api-key":
            return provider_api_key.strip()
    return None


def get_provider_and_url_by_model_sync(model_name: str) -> dict:
    """
    根据模型名称从数据库配置中查找对应的供应商和 API URL（同步版本，带元数据缓存）

    安全策略：
    - 缓存仅保存 provider + backend_url（不可敏感元数据）
    - api_key 通过占位符返回，调用方需通过 _resolve_api_key_sync 实时解析
    """
    cached = _model_metadata_cache.get(model_name)
    if cached:
        api_key = _resolve_api_key_sync(get_mongo_db_sync(), cached["provider"], None)
        return {
            "provider": cached["provider"],
            "backend_url": cached["backend_url"],
            "api_key": api_key,
        }

    try:
        db = get_mongo_db_sync()
        # 查询最新的活跃配置
        configs_collection = db.system_configs
        doc = configs_collection.find_one({"is_active": True}, sort=[("version", -1)])

        if doc and "llm_configs" in doc:
            llm_configs = doc["llm_configs"]

            for config_dict in llm_configs:
                if config_dict.get("model_name") == model_name:
                    provider = config_dict.get("provider")
                    api_base = config_dict.get("api_base")
                    model_api_key = config_dict.get("api_key")

                    providers_collection = db.llm_providers
                    provider_doc = providers_collection.find_one({"name": provider})

                    # 实时解析 API Key（不缓存）
                    api_key = _resolve_api_key_sync(db, provider, model_api_key)

                    if not api_key:
                        logger.warning(f"⚠️ [同步查询] 未找到 {provider} 的 API Key，请在 Web UI 配置管理中添加")

                    # 确定 backend_url
                    backend_url = None
                    if api_base:
                        backend_url = api_base
                        logger.info(f"✅ [同步查询] 模型 {model_name} 使用自定义 API: {api_base}")
                    elif provider_doc and provider_doc.get("default_base_url"):
                        backend_url = provider_doc["default_base_url"]
                        logger.info(f"✅ [同步查询] 模型 {model_name} 使用厂家默认 API: {backend_url}")
                    else:
                        backend_url = _get_default_backend_url(provider)
                        logger.warning(f"⚠️ [同步查询] 厂家 {provider} 没有配置 default_base_url，使用硬编码默认值")

                    # 仅缓存 provider + backend_url 元数据
                    _model_metadata_cache.set(
                        model_name,
                        {
                            "provider": provider,
                            "backend_url": backend_url,
                        },
                    )
                    return {
                        "provider": provider,
                        "backend_url": backend_url,
                        "api_key": api_key,
                    }
        logger.warning(f"⚠️ [同步查询] 数据库中未找到模型 {model_name}，使用默认映射")
        provider = _get_default_provider_by_model(model_name)

        # 尝试从厂家配置中获取 default_base_url 和 API Key
        try:
            providers_collection = db.llm_providers
            provider_doc = providers_collection.find_one({"name": provider})

            backend_url = _get_default_backend_url(provider)
            if provider_doc:
                if provider_doc.get("default_base_url"):
                    backend_url = provider_doc["default_base_url"]
                    logger.info(f"✅ [同步查询] 使用厂家 {provider} 的 default_base_url: {backend_url}")

            api_key = _resolve_api_key_sync(db, provider, None)
            if not api_key:
                logger.warning(f"⚠️ [同步查询] 厂家 {provider} 无 API Key，请在 Web UI 配置管理中添加")

            _model_metadata_cache.set(
                model_name,
                {
                    "provider": provider,
                    "backend_url": backend_url,
                },
            )
            return {
                "provider": provider,
                "backend_url": backend_url,
                "api_key": api_key,
            }
        except Exception as e:
            logger.warning(f"⚠️ [同步查询] 无法查询厂家配置: {e}")

        # 最后回退到硬编码的默认 URL
        result = {
            "provider": provider,
            "backend_url": _get_default_backend_url(provider),
            "api_key": None,
        }
        _model_metadata_cache.set(
            model_name,
            {
                "provider": provider,
                "backend_url": result["backend_url"],
            },
        )
        return result
    except Exception as e:
        logger.error(f"❌ [同步查询] 查找模型供应商失败: {e}", exc_info=True)
        provider = _get_default_provider_by_model(model_name)
        fallback_result = {
            "provider": provider,
            "backend_url": _get_default_backend_url(provider),
            "api_key": None,
        }
        _model_metadata_cache.set(
            model_name,
            {
                "provider": provider,
                "backend_url": fallback_result["backend_url"],
            },
        )
        return fallback_result


def _get_default_backend_url(provider: str) -> str:
    """根据供应商名称返回默认的 backend_url"""
    default_urls = {
        "google": "https://generativelanguage.googleapis.com/v1beta",
        "dashscope": "https://dashscope.aliyuncs.com/api/v1",
        "openai": "https://api.openai.com/v1",
        "deepseek": "https://api.deepseek.com",
        "anthropic": "https://api.anthropic.com",
        "openrouter": "https://openrouter.ai/api/v1",
        "qianfan": "https://qianfan.baidubce.com/v2",
        "302ai": "https://api.302.ai/v1",
    }

    url = default_urls.get(provider, "https://dashscope.aliyuncs.com/compatible-mode/v1")
    return url


def _get_default_provider_by_model(model_name: str) -> str:
    """根据模型名称返回默认的供应商映射"""
    model_provider_map = {
        "qwen-turbo": "dashscope",
        "qwen-plus": "dashscope",
        "qwen-max": "dashscope",
        "qwen-plus-latest": "dashscope",
        "qwen-max-longcontext": "dashscope",
        "gpt-3.5-turbo": "openai",
        "gpt-4": "openai",
        "gpt-4-turbo": "openai",
        "gpt-4o": "openai",
        "gpt-4o-mini": "openai",
        "gemini-pro": "google",
        "gemini-2.0-flash": "google",
        "gemini-2.0-flash-thinking-exp": "google",
        "deepseek-chat": "deepseek",
        "deepseek-coder": "deepseek",
        "deepseek-v4-flash": "deepseek",
        "deepseek-v4-pro": "deepseek",
        "deepseek-reasoner": "deepseek",
        "glm-4": "zhipu",
        "glm-3-turbo": "zhipu",
        "chatglm3-6b": "zhipu",
    }
    provider = model_provider_map.get(model_name, "dashscope")
    return provider


# DeepSeek 旧模型弃用提醒（模块级常量，避免重复定义）
_DEPRECATED_MODELS = {
    "deepseek-chat": ("deepseek-v4-flash", "2026/07/24"),
    "deepseek-reasoner": ("deepseek-v4-pro", "2026/07/24"),
}


def create_analysis_config(
    selected_analysts: list,
    analyst_model: str,
    debate_model: str,
    llm_provider: str,
    market_type: str = "A股",
    analyst_model_config: dict = None,
    debate_model_config: dict = None,
) -> dict:
    """创建分析配置"""

    # 统一复制默认配置
    config = DEFAULT_CONFIG.copy()
    config["llm_provider"] = llm_provider
    config["debate_llm"] = debate_model
    config["analyst_llm"] = analyst_model

    for model_name in [analyst_model, debate_model]:
        if model_name in _DEPRECATED_MODELS:
            replacement, date = _DEPRECATED_MODELS[model_name]
            logger.warning(f"[Deprecation] 模型 '{model_name}' 将于 {date} 弃用，请迁移至 '{replacement}'")

    # 轮次由阶段配置决定
    config["max_debate_rounds"] = 1
    config["max_risk_discuss_rounds"] = 1
    config["memory_enabled"] = True
    config["online_tools"] = True

    try:
        analyst_provider_info = get_provider_and_url_by_model_sync(analyst_model)
        debate_provider_info = get_provider_and_url_by_model_sync(debate_model)

        config["backend_url"] = analyst_provider_info["backend_url"]
        config["analyst_api_key"] = analyst_provider_info.get("api_key")
        config["debate_api_key"] = debate_provider_info.get("api_key")

        # 始终设置 per-model provider，让 create_llm() 精确路由
        config["analyst_provider"] = analyst_provider_info["provider"]
        config["debate_provider"] = debate_provider_info["provider"]
        config["analyst_backend_url"] = analyst_provider_info["backend_url"]
        config["debate_backend_url"] = debate_provider_info["backend_url"]
    except Exception as e:
        logger.warning(f"⚠️  无法从数据库获取 backend_url 和 API Key: {e}")
        config["backend_url"] = _get_default_backend_url(llm_provider)
        # 回退：使用传入的 llm_provider 作为两个模型的 provider
        config["analyst_provider"] = llm_provider
        config["debate_provider"] = llm_provider
        config["analyst_backend_url"] = config["backend_url"]
        config["debate_backend_url"] = config["backend_url"]

    config["selected_analysts"] = selected_analysts
    config["debug"] = False

    if analyst_model_config:
        config["analyst_model_config"] = analyst_model_config
    if debate_model_config:
        config["debate_model_config"] = debate_model_config

    # 阶段配置默认值（交易员始终执行）
    config.setdefault("phase2_enabled", False)
    config.setdefault("phase2_debate_rounds", 1)
    config.setdefault("phase3_enabled", False)
    config.setdefault("phase3_debate_rounds", 1)
    config.setdefault("phase4_enabled", True)
    config.setdefault("phase4_debate_rounds", 1)
    config.setdefault("max_debate_rounds", 1)
    config.setdefault("max_risk_discuss_rounds", 1)

    return config
