"""
Google Gemini 原生 SDK 适配器
使用 ChatGoogleGenerativeAI 直接调用 Google API，保留原生 SDK 对 tool calling 的完整支持。
"""

import os
import time
from typing import Any, Dict, List, Optional

from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, LLMResult
from langchain_google_genai import ChatGoogleGenerativeAI

from app.engine.llm_adapters.base import BaseChatAdapter
from app.utils.logging_manager import get_logger

logger = get_logger("agents")


class GoogleNativeAdapter(ChatGoogleGenerativeAI, BaseChatAdapter):
    """Google Gemini 原生适配器，继承 ChatGoogleGenerativeAI + BaseChatAdapter"""

    def __init__(
        self,
        provider: str = "google",
        model: str = "gemini-2.0-flash",
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 4000,
        timeout: int = 180,
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

            # 优化返回内容格式
            if result and result.generations:
                for gen_list in result.generations:
                    if isinstance(gen_list, list):
                        for g in gen_list:
                            msg = getattr(g, "message", None)
                            if msg:
                                self._optimize_message_content(msg)
                    else:
                        msg = getattr(gen_list, "message", None)
                        if msg:
                            self._optimize_message_content(msg)

            self._track_token_usage(result, kwargs, start_time)
            return result

        except Exception as e:
            logger.error(f"[Google] 生成失败: {e}")
            error_str = str(e)
            if "API_KEY_INVALID" in error_str or "API key not valid" in error_str:
                content = "Google AI API Key 无效或未配置，请检查 GOOGLE_API_KEY。"
            elif "Connection" in error_str or "Network" in error_str:
                content = f"Google AI 网络连接失败: {error_str}"
            else:
                content = f"Google AI 调用失败: {error_str}"

            error_message = AIMessage(content=content)
            error_generation = ChatGeneration(message=error_message)
            return LLMResult(generations=[[error_generation]])

    def _optimize_message_content(self, message: BaseMessage):
        """优化新闻内容格式，保留原 Google 适配器的行为"""
        if not isinstance(message, AIMessage) or not message.content:
            return

        content = message.content
        news_indicators = [
            "股票", "公司", "市场", "投资", "财经", "证券", "交易",
            "涨跌", "业绩", "财报", "分析", "预测",
        ]
        is_news = any(kw in content for kw in news_indicators) and len(content) > 200
        if is_news:
            from app.utils.time_utils import get_current_date

            enhanced = content
            if "发布时间" not in content and "时间" not in content:
                enhanced = f"发布时间: {get_current_date()}\n\n{enhanced}"
            if "文章来源" not in content and "来源" not in content:
                enhanced = f"{enhanced}\n\n文章来源: Google AI 智能分析"
            message.content = enhanced
