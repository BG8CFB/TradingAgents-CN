"""
Anthropic Messages 协议客户端（官方 anthropic SDK）

- system 为顶层字段；消息体只含 user/assistant
- 工具调用：assistant 的 tool_use 块 ↔ user 的 tool_result 块（tool_use_id 配对）
- 发送前经 pairing.ensure_pairing 修复孤儿块（两种 API 均会 400）
- SDK 异常翻译为 core.errors 统一异常
"""

import json
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
    ToolDef,
    ToolResultBlock,
    ToolUseBlock,
    Usage,
)
from ..tools.pairing import ensure_pairing

_STOP_REASON_MAP = {
    "end_turn": StopReason.END_TURN,
    "stop_sequence": StopReason.STOP_SEQUENCE,
    "max_tokens": StopReason.MAX_TOKENS,
    "tool_use": StopReason.TOOL_USE,
}


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
        params.update(kwargs)

        # SSE 事件装配（参考 claude-code claude.ts 的事件处理）：
        # input_json_delta 增量拼接 tool_use.input，content_block_stop 时块完整
        text_parts: List[str] = []
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
                    elif et == "content_block_delta":
                        delta = event.delta
                        if delta.type == "text_delta":
                            text_parts.append(delta.text)
                            yield StreamEvent("text_delta", text=delta.text)
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
        for tb in tool_blocks:
            try:
                parsed = json.loads(tb["json"]) if tb["json"] else {}
            except json.JSONDecodeError:
                parsed = {}
            blocks.append(ToolUseBlock(id=tb["id"], name=tb["name"], input=parsed))
        # 有工具调用块时停止原因必然是 tool_use（个别网关不回传 stop_reason）
        if tool_blocks:
            stop_reason = StopReason.TOOL_USE
        yield StreamEvent(
            "message",
            response=ChatResponse(
                message=Message(role=Role.ASSISTANT, content=blocks),
                stop_reason=stop_reason,
                usage=usage,
                model=model_name,
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
