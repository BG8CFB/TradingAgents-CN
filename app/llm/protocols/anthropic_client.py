"""
Anthropic Messages 协议客户端（官方 anthropic SDK）

- system 为顶层字段；消息体只含 user/assistant
- 工具调用：assistant 的 tool_use 块 ↔ user 的 tool_result 块（tool_use_id 配对）
- 发送前经 pairing.ensure_pairing 修复孤儿块（两种 API 均会 400）
- SDK 异常翻译为 core.errors 统一异常
"""

import json
import logging
from typing import Any, AsyncIterator, Dict, List, Optional

from app.constants.llm_defaults import DEFAULT_MAX_TOKENS
from ..core.base import BaseLLMClient, StreamEvent
from ..core.errors import (
    AuthError,
    ContextWindowExceededError,
    LLMError,
    RateLimitError,
    TimeoutError_,
)
from ..core.types import (
    ChatResponse,
    Message,
    Role,
    StopReason,
    TextBlock,
    ThinkingBlock,
    ToolDef,
    ToolResultBlock,
    ToolUseBlock,
    Usage,
)
from ..tools.pairing import ensure_pairing

logger = logging.getLogger("app.llm.protocols.anthropic")

_STOP_REASON_MAP = {
    "end_turn": StopReason.END_TURN,
    "stop_sequence": StopReason.STOP_SEQUENCE,
    "max_tokens": StopReason.MAX_TOKENS,
    "tool_use": StopReason.TOOL_USE,
}

# Anthropic extended thinking 的 budget 下限（官方约束）
_MIN_THINKING_BUDGET = 1024


def _apply_thinking(params: Dict[str, Any], thinking_budget: Optional[int], max_tokens: Optional[int]) -> None:
    """开启 extended thinking（opt-in）。

    官方约束：budget_tokens ≥ 1024 且 < max_tokens；thinking 开启时
    temperature 必须为 1（显式覆盖调用方传入的 temperature）。
    """
    if not thinking_budget or thinking_budget <= 0:
        return
    eff_max = max_tokens or params.get("max_tokens") or 0
    budget = max(_MIN_THINKING_BUDGET, min(thinking_budget, eff_max - 1))
    if budget >= eff_max:
        logger.warning(
            f"[anthropic] max_tokens={eff_max} 过小，无法开启 thinking "
            f"(budget 至少 {_MIN_THINKING_BUDGET} 且须小于 max_tokens)，本次不开启"
        )
        return
    params["thinking"] = {"type": "enabled", "budget_tokens": budget}
    params["temperature"] = 1


def _translate_error(e: Exception) -> LLMError:
    """把 anthropic SDK 异常翻译为统一异常"""
    status = getattr(e, "status_code", None)
    msg = str(e)
    if status in (401, 403):
        return AuthError(msg, protocol="anthropic", status_code=status)
    if status == 429:
        return RateLimitError(msg, protocol="anthropic", status_code=status)
    if status == 400 and "prompt is too long" in msg.lower():
        return ContextWindowExceededError(msg, protocol="anthropic", status_code=status)
    if isinstance(e, TimeoutError):
        return TimeoutError_(msg, protocol="anthropic")
    return LLMError(msg, protocol="anthropic", status_code=status)


class AnthropicLLMClient(BaseLLMClient):
    protocol = "anthropic"

    def __init__(
        self,
        api_key: str,
        base_url: str,
        model: str,
        timeout: float = 300.0,
        max_tokens: int = DEFAULT_MAX_TOKENS,  # anthropic 必填参数的兜底默认
        temperature: Optional[float] = None,
    ):
        from anthropic import AsyncAnthropic

        self.model = model
        self.max_tokens = max_tokens
        # 实例级默认温度（数据库每模型配置烙入；调用处显式传参可覆盖）
        self.temperature = temperature
        # 火山 Ark 兼容 x-api-key 与 Authorization Bearer，SDK 默认走 x-api-key
        self._client = AsyncAnthropic(api_key=api_key, base_url=base_url, timeout=timeout)

    # ── canonical → Anthropic 请求体 ──────────────────────────────

    def _to_api_messages(self, messages: List[Message]) -> List[Dict[str, Any]]:
        ensure_pairing(messages)
        api_messages: List[Dict[str, Any]] = []
        for msg in messages:
            if msg.role == Role.SYSTEM:
                continue  # system 走顶层字段
            blocks = []
            for b in msg.blocks():
                if isinstance(b, TextBlock):
                    blocks.append({"type": "text", "text": b.text})
                elif isinstance(b, ThinkingBlock):
                    # thinking 块回传（signature 必带；thinking 开启的多轮会话
                    # 缺失会被 API 400 拒绝）。thinking 必须位于消息块序列首位
                    blocks.insert(0, {
                        "type": "thinking", "thinking": b.thinking, "signature": b.signature,
                    })
                elif isinstance(b, ToolUseBlock):
                    blocks.append({"type": "tool_use", "id": b.id, "name": b.name, "input": b.input})
                elif isinstance(b, ToolResultBlock):
                    blocks.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": b.tool_use_id,
                            "content": b.content,
                            "is_error": b.is_error,
                        }
                    )
            if blocks:
                api_messages.append({"role": msg.role.value, "content": blocks})
        return api_messages

    def _to_api_tools(self, tools: Optional[List[ToolDef]]) -> Optional[List[Dict[str, Any]]]:
        if not tools:
            return None
        return [
            {"name": t.name, "description": t.description, "input_schema": t.params_schema or {"type": "object"}}
            for t in tools
        ]

    def _response_to_canonical(self, resp: Any) -> ChatResponse:
        blocks: List[Any] = []
        for b in resp.content:
            if b.type == "text":
                blocks.append(TextBlock(text=b.text))
            elif b.type == "tool_use":
                blocks.append(ToolUseBlock(id=b.id, name=b.name, input=dict(b.input or {})))
        usage = Usage(
            input_tokens=getattr(resp.usage, "input_tokens", 0) or 0,
            output_tokens=getattr(resp.usage, "output_tokens", 0) or 0,
            cache_creation_input_tokens=getattr(resp.usage, "cache_creation_input_tokens", 0) or 0,
            cache_read_input_tokens=getattr(resp.usage, "cache_read_input_tokens", 0) or 0,
        )
        return ChatResponse(
            message=Message(role=Role.ASSISTANT, content=blocks),
            stop_reason=_STOP_REASON_MAP.get(resp.stop_reason, StopReason.OTHER),
            usage=usage,
            model=resp.model,
            raw=resp,
        )

    # ── 接口实现 ──────────────────────────────────────────────────

    async def chat(
        self,
        messages: List[Message],
        *,
        system: Optional[str] = None,
        tools: Optional[List[ToolDef]] = None,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        thinking_budget: Optional[int] = None,
        **kwargs,
    ) -> ChatResponse:
        params: Dict[str, Any] = {
            "model": self.model,
            "max_tokens": max_tokens or self.max_tokens,
            "messages": self._to_api_messages(messages),
        }
        if system:
            params["system"] = system
        if tools:
            params["tools"] = self._to_api_tools(tools)
        eff_temp = temperature if temperature is not None else self.temperature
        if eff_temp is not None:
            params["temperature"] = eff_temp
        _apply_thinking(params, thinking_budget, max_tokens or self.max_tokens)
        params.update(kwargs)
        try:
            resp = await self._client.messages.create(**params)
        except Exception as e:  # noqa: BLE001 - 统一翻译
            raise _translate_error(e) from e
        return self._response_to_canonical(resp)

    async def chat_stream(
        self,
        messages: List[Message],
        *,
        system: Optional[str] = None,
        tools: Optional[List[ToolDef]] = None,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        thinking_budget: Optional[int] = None,
        **kwargs,
    ) -> AsyncIterator[StreamEvent]:
        params: Dict[str, Any] = {
            "model": self.model,
            "max_tokens": max_tokens or self.max_tokens,
            "messages": self._to_api_messages(messages),
        }
        if system:
            params["system"] = system
        if tools:
            params["tools"] = self._to_api_tools(tools)
        eff_temp = temperature if temperature is not None else self.temperature
        if eff_temp is not None:
            params["temperature"] = eff_temp
        _apply_thinking(params, thinking_budget, max_tokens or self.max_tokens)
        params.update(kwargs)

        # SSE 事件装配（参考 claude-code claude.ts 的事件处理）：
        # input_json_delta 增量拼接 tool_use.input，content_block_stop 时块完整
        # extended thinking（opt-in：请求需带 thinking={type,budget_tokens}，
        # 经 kwargs 透传）→ thinking_delta 聚合，经 raw 交给 runner 发 thinking 事件
        text_parts: List[str] = []
        thinking_parts: List[str] = []
        signature_parts: List[str] = []  # thinking 块签名（多轮回传校验必带）
        tool_blocks: List[Any] = []
        usage = Usage()
        stop_reason = StopReason.OTHER
        model_name = self.model

        try:
            async with self._client.messages.stream(**params) as stream:
                async for event in stream:
                    et = event.type
                    if et == "content_block_start":
                        block = event.content_block
                        if block.type == "tool_use":
                            tool_blocks.append({"id": block.id, "name": block.name, "json": ""})
                    # thinking 块的 signature_delta 仅为多轮回传校验用，
                    # canonical 层不回传 thinking 块，无需收集
                    elif et == "content_block_delta":
                        delta = event.delta
                        if delta.type == "text_delta":
                            text_parts.append(delta.text)
                            yield StreamEvent("text_delta", text=delta.text)
                        elif delta.type == "thinking_delta":
                            thinking_parts.append(delta.thinking)
                        elif delta.type == "signature_delta":
                            signature_parts.append(getattr(delta, "signature", "") or "")
                        elif delta.type == "input_json_delta":
                            if tool_blocks:
                                tool_blocks[-1]["json"] += delta.partial_json
                    elif et == "message_delta":
                        if getattr(event.delta, "stop_reason", None):
                            stop_reason = _STOP_REASON_MAP.get(event.delta.stop_reason, StopReason.OTHER)
                        if getattr(event, "usage", None):
                            usage.output_tokens = getattr(event.usage, "output_tokens", 0) or usage.output_tokens
                    elif et == "message_start":
                        u = getattr(event.message, "usage", None)
                        if u:
                            usage.input_tokens = getattr(u, "input_tokens", 0) or 0
                            # 缓存 token 只在 message_start 的 usage 中回传（message_delta 仅有 output）
                            usage.cache_creation_input_tokens = (
                                getattr(u, "cache_creation_input_tokens", 0) or 0
                            )
                            usage.cache_read_input_tokens = getattr(u, "cache_read_input_tokens", 0) or 0
                        model_name = getattr(event.message, "model", model_name)
        except Exception as e:  # noqa: BLE001
            raise _translate_error(e) from e

        blocks: List[Any] = [TextBlock(text=t) for t in text_parts if t]
        # thinking 开启时 canonical 保留 thinking 块（含 signature）：
        # 多轮工具循环回传历史时 API 要求 assistant 消息携带原 thinking 块；
        # thinking 块必须位于块序列首位
        if thinking_parts:
            blocks.insert(0, ThinkingBlock(
                thinking="".join(thinking_parts),
                signature="".join(signature_parts),
            ))
        for tb in tool_blocks:
            try:
                parsed = json.loads(tb["json"]) if tb["json"] else {}
            except json.JSONDecodeError:
                parsed = {}
            blocks.append(ToolUseBlock(id=tb["id"], name=tb["name"], input=parsed))
        # 有工具调用块时停止原因必然是 tool_use（个别网关不回传 stop_reason）
        if tool_blocks:
            stop_reason = StopReason.TOOL_USE

        # thinking 经 raw 透传（runner._extract_thinking_text 提取并发 thinking 事件）；
        # 流式无完整 SDK 响应对象，以轻量命名空间模拟 message.content 结构
        raw_thinking = None
        if thinking_parts:
            from types import SimpleNamespace

            raw_thinking = SimpleNamespace(
                content=[SimpleNamespace(type="thinking", thinking="".join(thinking_parts))]
            )

        yield StreamEvent(
            "message",
            response=ChatResponse(
                message=Message(role=Role.ASSISTANT, content=blocks),
                stop_reason=stop_reason,
                usage=usage,
                model=model_name,
                raw=raw_thinking,
            ),
        )

    async def count_tokens(self, messages: List[Message]) -> int:
        # chars/4 粗估；精确值以 usage 回传为准（compact/token_counter.py 负责综合）
        total = 0
        for m in messages:
            for b in m.blocks():
                if isinstance(b, ToolUseBlock):
                    total += len(b.name) + len(json.dumps(b.input, ensure_ascii=False))
                else:
                    text = getattr(b, "text", None) or getattr(b, "content", "") or ""
                    total += len(str(text))
        return total // 4
