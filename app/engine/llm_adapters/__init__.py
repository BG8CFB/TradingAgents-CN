"""
LLM 适配器包
提供统一的 LLM 创建接口。

推荐用法:
    from app.engine.llm_adapters import create_llm
    llm = create_llm(provider="deepseek", model="deepseek-chat", api_key="...")
"""

from app.engine.llm_adapters.factory import create_llm, PROVIDER_DEFAULTS
from app.engine.llm_adapters.openai_compatible import OpenAICompatibleAdapter
from app.engine.llm_adapters.anthropic_adapter import AnthropicAdapter
from app.engine.llm_adapters.google_native import GoogleNativeAdapter
from app.engine.llm_adapters.base import BaseChatAdapter

__all__ = [
    "create_llm",
    "PROVIDER_DEFAULTS",
    "OpenAICompatibleAdapter",
    "AnthropicAdapter",
    "GoogleNativeAdapter",
    "BaseChatAdapter",
]
