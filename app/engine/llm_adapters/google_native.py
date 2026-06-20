"""
Google Gemini 原生 SDK 适配器
使用 ChatGoogleGenerativeAI 直接调用 Google API，保留原生 SDK 对 tool calling 的完整支持。
"""

import time
from typing import List, Optional

try:
    from google.api_core.exceptions import GoogleAPIError
except ImportError:
    GoogleAPIError = Exception  # type: ignore[misc,assignment]

from langchain_core.messages import BaseMessage
from langchain_core.outputs import LLMResult
from langchain_google_genai import ChatGoogleGenerativeAI

from app.engine.llm_adapters.base import BaseChatAdapter
from app.utils.logging_manager import get_logger
from app.constants.llm_defaults import DEFAULT_MAX_TOKENS, DEFAULT_TEMPERATURE, DEFAULT_TIMEOUT

logger = get_logger("agents")


class GoogleNativeAdapter(ChatGoogleGenerativeAI, BaseChatAdapter):
    """Google Gemini 原生适配器，继承 ChatGoogleGenerativeAI + BaseChatAdapter"""

    def __init__(
        self,
        provider: str = "google",
        model: str = "gemini-2.0-flash",
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        temperature: float = DEFAULT_TEMPERATURE,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        timeout: int = DEFAULT_TIMEOUT,
        **kwargs,
    ):
        object.__setattr__(self, "_provider_name", provider)
        object.__setattr__(self, "_model_name_alias", model)

        resolved_key = self.resolve_api_key(provider, api_key, "GOOGLE_API_KEY")
        if not resolved_key:
            raise ValueError(
                "Google API 密钥未找到。"
                "请在 Web 界面配置 API Key 或设置 GOOGLE_API_KEY 环境变量。"
            )

        kwargs.setdefault("temperature", temperature)
        kwargs.setdefault("max_tokens", max_tokens)
        kwargs.setdefault("timeout", timeout)
        kwargs["google_api_key"] = resolved_key

        # base_url 处理：区分 Google 官方域名和中转地址
        if base_url:
            base_url = base_url.rstrip("/")
            is_google_official = "generativelanguage.googleapis.com" in base_url
            if is_google_official:
                # SDK 会自动添加版本路径，只保留域名
                for suffix in ("/v1beta", "/v1"):
                    if base_url.endswith(suffix):
                        base_url = base_url[: -len(suffix)]
                        break
            # 通过 client_options 传递端点
            kwargs["client_options"] = {"api_endpoint": base_url}

        super().__init__(model=model, **kwargs)

        object.__setattr__(self, "_provider_name", provider)
        object.__setattr__(self, "_model_name_alias", model)

        logger.info(f"[{provider}] Google 原生适配器初始化完成 model={model}")

    @property
    def model_name(self) -> str:
        m = self.model
        if m and m.startswith("models/"):
            return m[7:]
        return m or "unknown"

    def _generate(self, messages: List[BaseMessage], stop=None, **kwargs) -> LLMResult:
        start_time = time.time()
        try:
            result = super()._generate(messages, stop, **kwargs)
            self._track_token_usage(result, kwargs, start_time)
            return result

        except GoogleAPIError as e:
            logger.error(f"[Google] 生成失败: {e}")
            raise

        except Exception as e:
            logger.error(f"[Google] 未知错误: {e}")
            raise
