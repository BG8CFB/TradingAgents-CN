"""
OpenAI 兼容协议适配器
覆盖所有使用 OpenAI 兼容 API 的 provider：DeepSeek、DashScope、智谱、千帆、
SiliconFlow、OpenRouter、Ollama、自定义端点等。
"""

import time
from typing import Any, Callable, Dict, List, Optional

from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatResult
from langchain_openai import ChatOpenAI

from app.engine.llm_adapters.base import BaseChatAdapter
from app.utils.logging_manager import get_logger
from app.constants.llm_defaults import DEFAULT_MAX_TOKENS, DEFAULT_TEMPERATURE, DEFAULT_TIMEOUT

logger = get_logger("agents")


# ── DeepSeek Thinking Mode 兼容 ────────────────────────────────────
#
# 问题背景：
#   DeepSeek V4 的 thinking mode 会在 API 响应中返回 reasoning_content 字段。
#   LangChain 的 ChatOpenAI 在两个关键环节丢失了此字段：
#
#   1. 响应解析（_convert_dict_to_message）：
#      只提取 content / tool_calls / function_call / audio 到 AIMessage，
#      reasoning_content 被完全丢弃。这意味着 AIMessage.additional_kwargs
#      中永远不会包含 reasoning_content。
#
#   2. 请求序列化（_convert_message_to_dict）：
#      即使手动将 reasoning_content 放入 additional_kwargs，
#      _convert_message_to_dict 也不会将其序列化到请求的 message dict 中。
#      DeepSeek 要求在多轮工具调用中回传 assistant 消息的 reasoning_content，
#      否则返回 HTTP 400。
#
#   因此需要：
#   - 覆盖 _create_chat_result 从原始响应中提取 reasoning_content
#   - monkey-patch _convert_message_to_dict 在请求时注入 reasoning_content


def _is_deepseek_thinking_model(provider: str, model_name: str) -> bool:
    """判断是否为 DeepSeek thinking mode 模型（含 reasoning_content 的场景）

    DeepSeek V4 模型在 thinking mode 下会返回 reasoning_content 字段，
    需要在多轮工具调用中正确回传。保守策略：所有 DeepSeek 模型都启用
    reasoning_content 补丁（非 thinking mode 模型不会有此字段，补丁无副作用）。
    """
    if provider != "deepseek":
        return False
    # 所有 deepseek-* 模型启用补丁（保守策略，无副作用）
    return model_name.startswith("deepseek-")


class OpenAICompatibleAdapter(ChatOpenAI, BaseChatAdapter):
    """
    统一的 OpenAI 兼容适配器，通过 provider 参数区分不同厂家。
    继承 ChatOpenAI 以复用 OpenAI API 协议实现。
    """

    def __init__(
        self,
        provider: str = "openai",
        model: str = "gpt-4o-mini",
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        temperature: float = DEFAULT_TEMPERATURE,
        max_tokens: Optional[int] = None,
        timeout: int = DEFAULT_TIMEOUT,
        api_key_env: Optional[str] = None,
        **kwargs,
    ):
        from app.engine.llm_adapters.factory import PROVIDER_DEFAULTS

        defaults = PROVIDER_DEFAULTS.get(provider, {})

        # 解析 base_url: 显式参数 > 注册表默认值
        resolved_url = base_url or defaults.get("base_url")

        # 解析 api_key_env: 显式参数 > 注册表默认值
        resolved_env = api_key_env or defaults.get("api_key_env")

        # 解析 API Key: 显式参数 > 环境变量
        resolved_key = self.resolve_api_key(provider, api_key, resolved_env)

        # max_tokens 内部 fallback：显式 None → 使用全局默认值
        if max_tokens is None:
            max_tokens = DEFAULT_MAX_TOKENS

        # 本地模型（Ollama 等）允许空 API Key
        allow_no_key = defaults.get("allow_no_key", False)
        if not resolved_key and not allow_no_key:
            raise ValueError(
                f"{provider} API 密钥未找到。"
                f"请在 Web 界面配置 API Key (设置 -> 大模型厂家)"
                f"或设置 {resolved_env or provider.upper() + '_API_KEY'} 环境变量。"
            )

        # 千帆 API Key 格式校验
        if provider == "qianfan" and resolved_key and not resolved_key.startswith("bce-v3/"):
            raise ValueError("QIANFAN_API_KEY 格式错误，应为: bce-v3/ALTAK-xxx/xxx")

        # 写入私有属性（在 super().__init__ 之前和之后各写一次，防 Pydantic 重置）
        object.__setattr__(self, "_provider_name", provider)
        object.__setattr__(self, "_model_name_alias", model)
        object.__setattr__(self, "_pre_generate_hook", self._build_pre_hook(provider))

        # 构造 ChatOpenAI 参数
        openai_kwargs: Dict[str, Any] = {
            "model": model,
            "temperature": temperature,
            "max_tokens": max_tokens,
            **kwargs,
        }
        if resolved_url:
            openai_kwargs["base_url"] = resolved_url
        if resolved_key:
            openai_kwargs["api_key"] = resolved_key

        # ChatOpenAI 的 timeout 参数名
        openai_kwargs["timeout"] = timeout

        super().__init__(**openai_kwargs)

        # 再次确保私有属性存在
        object.__setattr__(self, "_provider_name", provider)
        object.__setattr__(self, "_model_name_alias", model)

        logger.info(f"[{provider}] 适配器初始化完成 model={model} url={resolved_url}")

    # ── Provider 特殊钩子 ─────────────────────────────────────

    @staticmethod
    def _build_pre_hook(provider: str) -> Optional[Callable]:
        """为特定 provider 构造生成前钩子"""
        if provider == "qianfan":
            return "_truncate_messages_for_qianfan"
        return None

    def _truncate_messages_for_qianfan(
        self, messages: List[BaseMessage], max_tokens: int = 4500
    ) -> List[BaseMessage]:
        """千帆模型输入 token 截断"""
        truncated = []
        total = 0
        for msg in reversed(messages):
            chars = len(str(getattr(msg, "content", "")))
            tokens = max(1, chars // 2)
            if total + tokens <= max_tokens:
                truncated.insert(0, msg)
                total += tokens
            else:
                if not truncated:
                    max_chars = (max_tokens - 100) * 2
                    msg.content = str(msg.content)[:max_chars] + "...(内容已截断)"
                    truncated.insert(0, msg)
                break
        if len(truncated) < len(messages):
            logger.warning(
                f"千帆模型输入过长，已截断 {len(messages) - len(truncated)} 条消息"
            )
        return truncated

    # ── 响应处理：保留 reasoning_content ──────────────────────

    def _create_chat_result(
        self,
        response: Any,
        generation_info: Optional[Dict[str, Any]] = None,
    ) -> ChatResult:
        """
        覆盖父类的 _create_chat_result，在标准解析后注入 DeepSeek 的
        reasoning_content 到 AIMessage.additional_kwargs。

        LangChain 的 _convert_dict_to_message 只提取标准 OpenAI 字段，
        会丢弃 DeepSeek 的 reasoning_content。我们通过 _inject_reasoning
        从原始响应中提取并注入。
        """
        result = super()._create_chat_result(response, generation_info)

        # 注入 reasoning_content（仅对 DeepSeek 等推理模型有意义）
        self._inject_reasoning_from_response(response, result)

        return result

    def _inject_reasoning_from_response(
        self, response: Any, result: ChatResult
    ) -> None:
        """从原始 API 响应中提取 reasoning_content，注入到 AIMessage。

        LangChain 的 _convert_dict_to_message 只处理标准 OpenAI 字段，
        不会提取 reasoning_content。这个方法在 _create_chat_result 之后
        调用，直接从原始响应 dict 中提取并注入。

        这样 reasoning_content 会在 AIMessage.additional_kwargs 中保存，
        后续多轮对话时 monkey-patch 会将它序列化回请求消息中。
        """
        provider = getattr(self, "_provider_name", "")
        if provider != "deepseek":
            return

        # 获取原始响应 dict
        response_dict = response if isinstance(response, dict) else response.model_dump()

        choices = response_dict.get("choices") or []
        for i, choice in enumerate(choices):
            if i >= len(result.generations):
                break
            msg_dict = choice.get("message", {})
            reasoning = msg_dict.get("reasoning_content")
            if reasoning is None:
                continue

            ai_msg = result.generations[i].message
            if isinstance(ai_msg, AIMessage):
                ai_msg.additional_kwargs["reasoning_content"] = reasoning
                logger.debug(
                    f"[deepseek] 已注入 reasoning_content "
                    f"({len(reasoning)} 字符) 到 AIMessage.additional_kwargs"
                )

    # ── 生成方法 ──────────────────────────────────────────────

    def _generate(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Optional[CallbackManagerForLLMRun] = None,
        **kwargs: Any,
    ) -> ChatResult:
        start_time = time.time()

        # 千帆截断钩子
        hook = getattr(self, "_pre_generate_hook", None)
        if hook == "_truncate_messages_for_qianfan":
            messages = self._truncate_messages_for_qianfan(messages)

        # DeepSeek thinking mode 兼容：
        # 1. _create_chat_result（响应方向）：已在上面覆盖，自动注入 reasoning_content
        # 2. _convert_message_to_dict（请求方向）：需要 monkey-patch 以回传 reasoning_content
        provider = getattr(self, "_provider_name", "")
        model_name = getattr(self, "model_name", None) or getattr(self, "_model_name_alias", "")
        needs_reasoning_fix = _is_deepseek_thinking_model(provider, model_name)

        if needs_reasoning_fix:
            result = self._generate_with_reasoning_fix(
                messages, stop, run_manager, **kwargs
            )
        else:
            result = super()._generate(messages, stop, run_manager, **kwargs)

        # 修复 content 为空的情况：部分模型（如 Qwen3.6 + Ollama）
        # 在 think 模式下将实际回复放在非标准 reasoning 字段中，
        # LangChain 解析时丢弃了该字段，导致 content 为空。
        self._fix_empty_content(result, messages)

        self._track_token_usage(result, kwargs, start_time)
        return result

    def _generate_with_reasoning_fix(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Optional[CallbackManagerForLLMRun] = None,
        **kwargs: Any,
    ) -> ChatResult:
        """
        DeepSeek thinking mode 的 _generate 包装。

        通过临时 monkey-patch langchain_openai.chat_models.base 模块的
        _convert_message_to_dict 函数，确保 AIMessage 的 reasoning_content
        被注入到序列化后的 dict 中。调用完成后恢复原函数。

        仅对 DeepSeek thinking mode 模型生效，不影响其他 provider。

        注意：reasoning_content 的来源是 _create_chat_result 中
        _inject_reasoning_from_response 方法从原始响应中提取并注入的。
        """
        import langchain_openai.chat_models.base as _lc_openai_base

        _original_fn = getattr(_lc_openai_base, "_convert_message_to_dict", None)
        if _original_fn is None:
            logger.warning(
                "[deepseek] 无法获取 LangChain _convert_message_to_dict，"
                "跳过 reasoning_content 注入（可能触发 400 错误）"
            )
            return super()._generate(messages, stop, run_manager, **kwargs)

        def _patched_convert_message_to_dict(message, *args, **ckwargs):
            msg_dict = _original_fn(message, *args, **ckwargs)
            # 对 AIMessage，注入 additional_kwargs 中的 reasoning_content
            if isinstance(message, AIMessage) and msg_dict.get("role") == "assistant":
                reasoning = message.additional_kwargs.get("reasoning_content")
                if reasoning is not None:
                    msg_dict["reasoning_content"] = reasoning
            return msg_dict

        try:
            _lc_openai_base._convert_message_to_dict = _patched_convert_message_to_dict
            logger.debug(
                f"[deepseek] 已启用 reasoning_content 序列化补丁 "
                f"(messages 含 {sum(1 for m in messages if isinstance(m, AIMessage))} 条 AIMessage)"
            )
            result = super(OpenAICompatibleAdapter, self)._generate(
                messages, stop, run_manager, **kwargs
            )
            return result
        finally:
            # 确保恢复原函数，避免影响其他调用
            if _original_fn is not None:
                _lc_openai_base._convert_message_to_dict = _original_fn

    def _fix_empty_content(
        self, result: ChatResult, messages: List[BaseMessage]
    ) -> None:
        """回填空的 content — 从 additional_kwargs 中提取 reasoning_content"""
        provider = getattr(self, "_provider_name", "")
        for gen in result.generations:
            msg = getattr(gen, "message", None)
            if msg is None:
                continue
            content = getattr(msg, "content", None)
            has_tool_calls = bool(getattr(msg, "tool_calls", None))
            if (content is None or content == "") and not has_tool_calls:
                # 从 additional_kwargs 中提取 reasoning_content
                # （已由 _inject_reasoning_from_response 注入）
                reasoning = msg.additional_kwargs.get("reasoning_content")
                if reasoning:
                    msg.content = reasoning
                    logger.warning(
                        f"[{provider}] 模型返回了 reasoning_content 但 content 为空。"
                        f"已回填思考链内容 ({len(reasoning)} 字符) 作为回复。"
                        f"这通常意味着模型处于 thinking mode 但未生成最终答案。"
                    )
                # Ollama think 模式需要额外 API 调用获取 reasoning
                elif provider == "ollama":
                    reasoning = self._fetch_reasoning(messages)
                    if reasoning:
                        msg.content = reasoning
                        logger.debug(
                            f"[{provider}] "
                            f"content 为空，已从 reasoning 回填 ({len(reasoning)} 字符)"
                        )
                else:
                    logger.debug(f"[{provider}] content 为空，跳过 reasoning 回填")

    def _fetch_reasoning(self, messages: List[BaseMessage]) -> str:
        """用底层 OpenAI SDK 发起原生调用获取 reasoning 字段

        注意：此方法会发起一次额外的 API 调用。仅在 content 为空时触发。
        使用 getattr 安全获取模型属性，避免属性不存在时崩溃。
        """
        try:
            from openai import OpenAI

            api_key = self.openai_api_key
            if hasattr(api_key, "get_secret_value"):
                api_key = api_key.get_secret_value()

            # 安全获取模型名称，失败时直接返回空字符串
            model_name = getattr(self, 'model_name', None)
            if not model_name:
                # 尝试从 _model_name_alias 私有属性获取
                model_name = getattr(self, '_model_name_alias', None)
            if not model_name:
                logger.debug("无法获取模型名称，跳过 reasoning 回填")
                return ""

            client = OpenAI(
                api_key=api_key,
                base_url=self.openai_api_base or None,
            )

            openai_messages = []
            for m in messages:
                role = "user"
                if m.type == "system":
                    role = "system"
                elif m.type == "ai":
                    role = "assistant"
                openai_messages.append({"role": role, "content": str(m.content)})

            resp = client.chat.completions.create(
                model=model_name,
                messages=openai_messages,
                max_tokens=getattr(self, 'max_tokens', 200) or 200,
                temperature=getattr(self, 'temperature', DEFAULT_TEMPERATURE),
            )
            msg = resp.choices[0].message
            reasoning = getattr(msg, "reasoning_content", None) or getattr(msg, "reasoning", None) or ""
            return reasoning.strip() if reasoning else ""
        except Exception:
            return ""
