"""
Anthropic 协议适配器
覆盖 Anthropic Claude 系列模型。
"""

import time
from typing import Any, List, Optional

from langchain_anthropic import ChatAnthropic
from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.messages import BaseMessage
from langchain_core.outputs import ChatResult

from app.engine.llm_adapters.base import BaseChatAdapter
from app.utils.logging_manager import get_logger

logger = get_logger("agents")


class AnthropicAdapter(ChatAnthropic, BaseChatAdapter):
    """Anthropic Claude 适配器，继承 ChatAnthropic + BaseChatAdapter"""

    def __init__(
        self,
        provider: str = "anthropic",
        model: str = "claude-sonnet-4-20250514",
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 4000,
        timeout: int = 180,
        **kwargs,
    ):
        object.__setattr__(self, "_provider_name", provider)
        object.__setattr__(self, "_model_name_alias", model)

        resolved_key = self.resolve_api_key(provider, api_key, "ANTHROPIC_API_KEY")
        if not resolved_key:
            raise ValueError(
                "Anthropic API 密钥未找到。"
                "请在 Web 界面配置 API Key 或设置 ANTHROPIC_API_KEY 环境变量。"
            )

        init_kwargs: dict = {
            "model_name": model,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "timeout": timeout,
            "api_key": resolved_key,
            **kwargs,
        }
        if base_url:
            init_kwargs["base_url"] = base_url

        super().__init__(**init_kwargs)

        object.__setattr__(self, "_provider_name", provider)
        object.__setattr__(self, "_model_name_alias", model)

        logger.info(f"[{provider}] Anthropic 适配器初始化完成 model={model}")

    def _generate(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Optional[CallbackManagerForLLMRun] = None,
        **kwargs: Any,
    ) -> ChatResult:
        start_time = time.time()
        result = super()._generate(messages, stop, run_manager, **kwargs)
        self._track_token_usage(result, kwargs, start_time)
        return result
