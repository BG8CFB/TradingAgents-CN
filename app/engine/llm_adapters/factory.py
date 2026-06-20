"""
统一 LLM 工厂函数 + Provider 注册表
所有 LLM 实例创建的唯一入口点。
"""

from typing import Any, Dict, Optional

from app.utils.logging_manager import get_logger
from app.constants.llm_defaults import DEFAULT_MAX_TOKENS, DEFAULT_TEMPERATURE, DEFAULT_TIMEOUT

logger = get_logger("agents")

# ── Provider 注册表 ──────────────────────────────────────────────
# protocol: "openai" | "anthropic" | "google"
# base_url: 默认 API 地址（None 表示由调用方传入或从 DB 读取）
# allow_no_key: True 表示允许无 API Key（本地模型）
# API Key 从数据库 llm_providers 集合读取，不再从环境变量读取

PROVIDER_DEFAULTS: Dict[str, Dict[str, Any]] = {
    # ── OpenAI 兼容协议 ──────────────────────────────────────
    "openai": {
        "protocol": "openai",
        "base_url": "https://api.openai.com/v1",
    },
    "deepseek": {
        "protocol": "openai",
        "base_url": "https://api.deepseek.com",
    },
    "dashscope": {
        "protocol": "openai",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    },
    "zhipu": {
        "protocol": "openai",
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
    },
    "qianfan": {
        "protocol": "openai",
        "base_url": "https://qianfan.baidubce.com/v2",
    },
    "siliconflow": {
        "protocol": "openai",
        "base_url": None,
    },
    "openrouter": {
        "protocol": "openai",
        "base_url": "https://openrouter.ai/api/v1",
    },
    "ollama": {
        "protocol": "openai",
        "base_url": "http://localhost:11434/v1",
        "allow_no_key": True,
    },
    "alibaba": {
        "protocol": "openai",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    },
    # 聚合渠道
    "302ai": {
        "protocol": "openai",
        "base_url": None,
    },
    "oneapi": {
        "protocol": "openai",
        "base_url": None,
    },
    "newapi": {
        "protocol": "openai",
        "base_url": None,
    },
    "custom_openai": {
        "protocol": "openai",
        "base_url": None,
    },
    "custom_aggregator": {
        "protocol": "openai",
        "base_url": None,
    },
    # ── Anthropic 协议 ───────────────────────────────────────
    "anthropic": {
        "protocol": "anthropic",
        "base_url": None,
    },
    # ── Google 原生协议 ──────────────────────────────────────
    "google": {
        "protocol": "google",
        "base_url": None,
    },
}


def _normalize_base_url(provider: str, base_url: Optional[str]) -> Optional[str]:
    """自动修正已知的不兼容 URL"""
    if not base_url:
        return base_url

    # DashScope: 原生 API URL → OpenAI 兼容 URL
    if provider in ("dashscope", "alibaba"):
        if "/api/v1" in base_url and "compatible-mode" not in base_url:
            logger.warning(
                f"检测到 DashScope 原生 API URL ({base_url})，已切换为兼容模式"
            )
            return "https://dashscope.aliyuncs.com/compatible-mode/v1"

    return base_url


def _get_protocol(provider: str) -> str:
    """获取 provider 的协议类型，未知 provider 默认走 OpenAI 兼容"""
    defaults = PROVIDER_DEFAULTS.get(provider)
    if defaults:
        return defaults.get("protocol", "openai")
    return "openai"


def create_llm(
    provider: str,
    model: str,
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
    temperature: float = DEFAULT_TEMPERATURE,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    timeout: int = DEFAULT_TIMEOUT,
    **kwargs,
):
    """
    统一 LLM 工厂函数 — 所有 LLM 创建的唯一入口。

    根据 provider 协议类型路由到对应的适配器类：
    - "openai"  → OpenAICompatibleAdapter
    - "anthropic" → AnthropicAdapter
    - "google"  → GoogleNativeAdapter

    Args:
        provider: 供应商标识（如 "deepseek", "dashscope", "anthropic", "google"）
        model: 模型名称
        api_key: API Key（显式传入优先）
        base_url: API 地址（显式传入优先）
        temperature: 温度参数
        max_tokens: 最大 token 数
        timeout: 超时秒数

    Returns:
        LLM 实例（BaseChatAdapter 子类）
    """
    provider_lower = provider.lower()
    protocol = _get_protocol(provider_lower)
    normalized_url = _normalize_base_url(provider_lower, base_url)

    # 合并 provider 级默认参数（最低优先级，调用方 kwargs 可覆盖）
    provider_kwargs = PROVIDER_DEFAULTS.get(provider_lower, {}).get("provider_kwargs", {})
    merged_kwargs = {**provider_kwargs, **kwargs}

    logger.info(
        f"[Factory] 创建 LLM: provider={provider_lower} model={model} "
        f"protocol={protocol} url={normalized_url or '(default)'}"
    )

    if protocol == "google":
        from app.engine.llm_adapters.google_native import GoogleNativeAdapter

        return GoogleNativeAdapter(
            provider=provider_lower,
            model=model,
            api_key=api_key,
            base_url=normalized_url,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout=timeout,
            **merged_kwargs,
        )

    if protocol == "anthropic":
        from app.engine.llm_adapters.anthropic_adapter import AnthropicAdapter

        return AnthropicAdapter(
            provider=provider_lower,
            model=model,
            api_key=api_key,
            base_url=normalized_url,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout=timeout,
            **merged_kwargs,
        )

    # 默认: OpenAI 兼容协议
    from app.engine.llm_adapters.openai_compatible import OpenAICompatibleAdapter

    return OpenAICompatibleAdapter(
        provider=provider_lower,
        model=model,
        api_key=api_key,
        base_url=normalized_url,
        temperature=temperature,
        max_tokens=max_tokens,
        timeout=timeout,
        **merged_kwargs,
    )
