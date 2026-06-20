"""
OpenAI 兼容协议适配器
覆盖所有使用 OpenAI 兼容 API 的 provider：DeepSeek、DashScope、智谱、千帆、
SiliconFlow、OpenRouter、Ollama、自定义端点等。
"""

import copy
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

# Ollama reasoning 回填调用计数器（防止同一会话多次调用）
_ollama_fetch_count: dict[int, int] = {}


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
    return model_name.startswith("deepseek-")


def _is_deepseek_v4_model(provider: str, model_name: str) -> bool:
    """判断是否为 DeepSeek V4 模型（支持可控思考模式）

    V4 模型支持通过 extra_body={"thinking": {"type": "enabled/disabled"}}
    显式控制思考模式。旧模型（deepseek-chat、deepseek-reasoner）不支持此参数。
    """
    if provider != "deepseek":
        return False
    return model_name.startswith("deepseek-v4")


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

        # DeepSeek thinking mode 兼容（per-instance 一次性预处理，无 monkey-patch）：
        # 把每个 AIMessage.additional_kwargs.reasoning_content 作为前缀合并到 content，
        # 让 LangChain 的标准序列化（_convert_message_to_dict）能正确把它放入请求 dict。
        # 旧实现通过模块级 monkey-patch _convert_message_to_dict 实现，存在并发数据竞争
        # （refcount 跨实例共享），且 patch 安装/恢复依赖时序。本方案彻底移除模块级状态，
        # 每个 _generate 调用独立处理自己的 messages，无并发问题。
        provider = getattr(self, "_provider_name", "")
        model_name = getattr(self, "model_name", None) or getattr(self, "_model_name_alias", "")
        if _is_deepseek_thinking_model(provider, model_name):
            messages = self._merge_reasoning_into_content(messages)

        result = super()._generate(messages, stop, run_manager, **kwargs)

        # 修复 content 为空的情况：部分模型（如 Qwen3.6 + Ollama）
        # 在 think 模式下将实际回复放在非标准 reasoning 字段中，
        # LangChain 解析时丢弃了该字段，导致 content 为空。
        self._fix_empty_content(result, messages)

        self._track_token_usage(result, kwargs, start_time)
        return result

    @staticmethod
    def _merge_reasoning_into_content(
        messages: List[BaseMessage],
    ) -> List[BaseMessage]:
        """把 AIMessage.additional_kwargs.reasoning_content 合并到 content。

        DeepSeek thinking mode 要求多轮对话中把 assistant 的 reasoning_content
        回传给 API，否则返回 HTTP 400。LangChain 的 _convert_message_to_dict
        默认不会序列化 reasoning_content，因此把它直接拼到 content 字段，
        API 在请求 dict 中即能看到。

        设计要点：
        - 使用 copy.copy 浅拷贝每个 AIMessage，避免修改共享消息历史
        - reasoning_content 仅合并 assistant 角色（HumanMessage/SystemMessage 无此字段）
        - 合并后从 additional_kwargs 中删除 reasoning_content，避免双重发送
        """
        if not messages:
            return messages

        result: List[BaseMessage] = []
        for msg in messages:
            if not isinstance(msg, AIMessage):
                result.append(msg)
                continue
            reasoning = msg.additional_kwargs.get("reasoning_content")
            if not reasoning:
                result.append(msg)
                continue
            # 浅拷贝以保留原 message 不可变；additional_kwargs 也需独立拷贝
            new_msg = copy.copy(msg)
            new_msg.additional_kwargs = {
                k: v for k, v in (msg.additional_kwargs or {}).items()
                if k != "reasoning_content"
            }
            original_content = msg.content or ""
            if isinstance(original_content, str):
                new_msg.content = (
                    f"[思考]\n{reasoning}\n[/思考]\n\n{original_content}"
                )
            else:
                # LangChain content 也可能是 list[ContentBlock]，此场景少见；
                # 在最前面插入一段文本块即可
                text_block = {
                    "type": "text",
                    "text": f"[思考]\n{reasoning}\n[/思考]\n\n",
                }
                if isinstance(original_content, list):
                    new_msg.content = [text_block] + list(original_content)
                else:
                    new_msg.content = text_block["text"] + str(original_content)
            result.append(new_msg)
        return result

    def _fix_empty_content(
        self, result: ChatResult, messages: List[BaseMessage]
    ) -> None:
        """回填空的 content — 处理不同 provider 的特殊情况"""
        provider = getattr(self, "_provider_name", "")
        for gen in result.generations:
            msg = getattr(gen, "message", None)
            if msg is None:
                continue
            content = getattr(msg, "content", None)
            has_tool_calls = bool(getattr(msg, "tool_calls", None))
            if (content is None or content == "") and not has_tool_calls:
                reasoning = msg.additional_kwargs.get("reasoning_content")

                if provider == "deepseek":
                    # DeepSeek 思考模式：content 为空意味着模型只产出了思考链
                    # 但没有生成最终答案。不应将 reasoning_content 回填到 content，
                    # 否则 Stage 2/3/4 的辩论论据、投资计划、JSON 输出都会变成思考链。
                    # 正常情况下 DeepSeek V4 会同时返回 reasoning_content 和 content，
                    # content 为空是极罕见的边界情况（如 token 耗尽），此处作为安全兜底。
                    logger.warning(
                        f"[deepseek] content 为空但存在 reasoning_content "
                        f"({len(reasoning) if reasoning else 0} 字符)。"
                        f"模型可能在思考后未生成最终答案。"
                    )
                elif reasoning:
                    # 非 DeepSeek 模型（Ollama 等）保留原有回填逻辑
                    msg.content = reasoning
                    logger.warning(
                        f"[{provider}] 模型返回了 reasoning_content 但 content 为空。"
                        f"已回填思考链内容 ({len(reasoning)} 字符) 作为回复。"
                        f"这通常意味着模型处于 thinking mode 但未生成最终答案。"
                    )
                elif provider == "ollama":
                    # Ollama think 模式需要额外 API 调用获取 reasoning
                    adapter_id = id(self)
                    if _ollama_fetch_count.get(adapter_id, 0) < 1:
                        _ollama_fetch_count[adapter_id] = _ollama_fetch_count.get(adapter_id, 0) + 1
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
        except Exception as e:
            logger.debug(f"提取推理内容失败: {e}")
            return ""
