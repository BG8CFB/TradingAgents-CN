"""
Embedding Provider 解析器

封装多 provider 的 embedding 初始化降级链：
DashScope → OpenAI 兼容 → DISABLED

API Key 从数据库 llm_providers 集合读取，不从环境变量读取。
"""

from dataclasses import dataclass
from typing import Optional, Any

from app.core.env import get_env
from app.utils.logging_init import get_logger

logger = get_logger("agents.utils.embedding_resolver")


@dataclass
class EmbeddingConfig:
    """解析后的 embedding 配置"""
    client: Any  # OpenAI client 实例、None（DashScope 模式）或 "DISABLED"
    embedding_model: str
    provider: str
    fallback_available: bool = False
    fallback_client: Any = None
    fallback_embedding: str = ""


def _get_api_key_from_db(provider: str) -> Optional[str]:
    """从数据库 llm_providers 集合读取 API Key"""
    try:
        from app.core.database import get_mongo_db_sync
        db = get_mongo_db_sync()
        doc = db.llm_providers.find_one({"name": provider, "is_active": True})
        if doc and doc.get("api_key"):
            key = doc["api_key"]
            if key and key.strip() and not key.startswith("your_"):
                return key.strip()
    except Exception as e:
        logger.debug(f"从 DB 读取 {provider} API Key 失败: {e}")
    return None


def resolve_embedding(provider: str, config: dict) -> EmbeddingConfig:
    """
    根据 provider 解析 embedding 配置，统一降级链：
    DashScope → OpenAI 兼容 → DISABLED

    Args:
        provider: LLM provider 名称
        config: 项目配置字典（包含 backend_url 等）

    Returns:
        EmbeddingConfig 数据类
    """
    provider_lower = (provider or "openai").lower()

    # 特殊情况：Ollama 本地模型
    backend_url = config.get("backend_url", "")
    if backend_url == "http://localhost:11434/v1":
        from openai import OpenAI
        return EmbeddingConfig(
            client=OpenAI(api_key="not-needed", base_url=backend_url),
            embedding_model="nomic-embed-text",
            provider=provider_lower,
        )

    # 主降级链：DashScope → OpenAI → DISABLED
    use_dashscope_providers = {
        "dashscope", "alibaba", "qianfan", "google", "openrouter",
    }

    if provider_lower in use_dashscope_providers or (
        provider_lower == "deepseek" and not _force_openai()
    ):
        result = _try_dashscope(provider_lower)
        if result is not None:
            return result

    # OpenAI 兼容降级
    openai_result = _try_openai(provider_lower, config)
    if openai_result is not None:
        return openai_result

    # 全部失败
    logger.warning(f"⚠️ [{provider_lower}] 无可用 embedding 服务，记忆功能已禁用")
    return EmbeddingConfig(client="DISABLED", embedding_model="", provider=provider_lower)


def _force_openai() -> bool:
    return get_env("FORCE_OPENAI_EMBEDDING", "false").lower() == "true"


def _try_dashscope(provider: str) -> Optional[EmbeddingConfig]:
    """尝试 DashScope embedding"""
    api_key = _get_api_key_from_db("dashscope")
    if not api_key:
        return None

    try:
        import dashscope
        from dashscope import TextEmbedding
        dashscope.api_key = api_key
        logger.info(f"💡 [{provider}] 使用 DashScope embedding")
        return EmbeddingConfig(
            client=None,
            embedding_model="text-embedding-v3",
            provider=provider,
        )
    except ImportError:
        logger.debug(f"⚠️ [{provider}] DashScope 包未安装")
        return None
    except Exception as e:
        logger.debug(f"⚠️ [{provider}] DashScope 初始化失败: {e}")
        return None


def _try_openai(provider: str, config: dict) -> Optional[EmbeddingConfig]:
    """尝试 OpenAI 兼容 embedding"""
    from openai import OpenAI

    openai_key = _get_api_key_from_db("openai")
    deepseek_key = _get_api_key_from_db("deepseek")

    if openai_key:
        base_url = config.get("backend_url", "https://api.openai.com/v1")
        logger.info(f"💡 [{provider}] 使用 OpenAI embedding (降级)")
        return EmbeddingConfig(
            client=OpenAI(api_key=openai_key, base_url=base_url),
            embedding_model="text-embedding-3-small",
            provider=provider,
        )

    if provider == "deepseek" and deepseek_key:
        logger.info(f"[{provider}] DeepSeek 不提供 Embedding API，跳过")

    return None
