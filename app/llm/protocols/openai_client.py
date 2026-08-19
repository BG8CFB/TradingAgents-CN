"""
OpenAI 兼容协议客户端（官方 openai SDK）

核心职责：
- canonical（Anthropic 风格 content blocks）↔ OpenAI chat/completions 消息双向转换
  - tool_use → assistant.tool_calls[{id, function:{name, arguments}}]
  - tool_result → role:"tool" 消息（必须排在同轮 user 文本之前，否则 OpenAI 400）
- 流式：stream_options.include_usage=true
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

_FINISH_MAP = {
    "stop": StopReason.END_TURN,
    "tool_calls": StopReason.TOOL_USE,
    "length": StopReason.MAX_TOKENS,
}


def _translate_error(e: Exception) -> LLMError:
    status = getattr(e, "status_code", None)
    msg = str(e)
    body = getattr(e, "body", None) or {}
    err = body.get("error", {}) if isinstance(body, dict) else {}
    code = err.get("code", "")
    if status in (401, 403) or code in ("invalid_api_key", "authentication_error"):
        return AuthError(msg, protocol="openai", status_code=status)
    if status == 429 or code == "rate_limit_exceeded":
        return RateLimitError(msg, protocol="openai", status_code=status)
    if "context_length_exceeded" in msg or code == "context_length_exceeded":
        return ContextWindowExceededError(msg, protocol="openai", status_code=status)
    if isinstance(e, TimeoutError):
        return TimeoutError_(msg, protocol="openai")
    return LLMError(msg, protocol="openai", status_code=status)


class OpenAILLMClient(BaseLLMClient):
    protocol = "openai"

    def __init__(
        self,
        api_key: str,
        base_url: str,
        model: str,
        timeout: float = 300.0,
        max_tokens: int = DEFAULT_MAX_TOKENS,  # 兜底默认（单一源头 llm_defaults）
        temperature: Optional[float] = None,
    ):
        from openai import AsyncOpenAI

        self.model = model
        self.max_tokens = max_tokens
        # 实例级默认温度（数据库每模型配置烙入；调用处显式传参可覆盖）
        self.temperature = temperature
        self._client = AsyncOpenAI(api_key=api_key, base_url=base_url, timeout=timeout)

    # ── canonical → OpenAI 消息 ───────────────────────────────────

    def _to_api_messages(self, messages: List[Message], system: Optional[str]) -> List[Dict[str, Any]]:
        """canonical → OpenAI 消息列表。

        关键顺序约束：一条 canonical user 消息若同时含 tool_result 与 text，
        必须先产出 role:"tool" 消息再产出 user 文本（OpenAI 要求 tool 消息
        紧跟对应的 assistant.tool_calls 之后）。
        """
        api_messages: List[Dict[str, Any]] = []
        if system:
            api_messages.append({"role": "system", "content": system})

        pending_tools: List[Dict[str, Any]] = []  # 暂存 tool 消息，保证先于 user 文本

        def flush_tools():
            api_messages.extend(pending_tools)
            pending_tools.clear()

        for msg in messages:
            if msg.role == Role.SYSTEM:
                api_messages.append({"role": "system", "content": str(msg.content)})
                continue

            for b in msg.blocks():
                if isinstance(b, TextBlock):
                    if msg.role == Role.ASSISTANT:
                        api_messages.append({"role": "assistant", "content": b.text})
                    else:
                        flush_tools()
                        api_messages.append({"role": "user", "content": b.text})
                elif isinstance(b, ToolUseBlock):
                    # tool_use 附着到 assistant 消息的 tool_calls
                    last = api_messages[-1] if api_messages else None
                    if not (last and last.get("role") == "assistant" and "tool_calls" in last):
                        last = {"role": "assistant", "content": "", "tool_calls": []}
                        api_messages.append(last)
                    last["tool_calls"].append(
                        {
                            "id": b.id,
                            "type": "function",
                            "function": {"name": b.name, "arguments": json.dumps(b.input, ensure_ascii=False)},
                        }
                    )
                elif isinstance(b, ToolResultBlock):
                    pending_tools.append(
                        {
                            "role": "tool",
                            "tool_call_id": b.tool_use_id,
                            "content": b.content,
                        }
                    )
        flush_tools()
        return api_messages

    def _to_api_tools(self, tools: Optional[List[ToolDef]]) -> Optional[List[Dict[str, Any]]]:
        if not tools:
            return None
        return [
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description,
                    "parameters": t.params_schema or {"type": "object"},
                },
            }
            for t in tools
        ]

    def _response_to_canonical(self, resp: Any) -> ChatResponse:
        choice = resp.choices[0] if resp.choices else None
        blocks: List[Any] = []
        finish = StopReason.OTHER
        if choice:
            msg = choice.message
            if msg.content:
                blocks.append(TextBlock(text=msg.content))
            for tc in getattr(msg, "tool_calls", None) or []:
                fn = tc.function
                try:
                    args = json.loads(fn.arguments) if fn.arguments else {}
                except json.JSONDecodeError:
                    args = {"_raw": fn.arguments}
                blocks.append(ToolUseBlock(id=tc.id, name=fn.name, input=args))
            finish = _FINISH_MAP.get(choice.finish_reason, StopReason.OTHER)
            if any(isinstance(b, ToolUseBlock) for b in blocks):
                finish = StopReason.TOOL_USE
        usage = Usage()
        if resp.usage:
            # 部分网关不回传 prompt_tokens_details，getattr 链兜底
            details = getattr(resp.usage, "prompt_tokens_details", None)
            usage = Usage(
                input_tokens=getattr(resp.usage, "prompt_tokens", 0) or 0,
                output_tokens=getattr(resp.usage, "completion_tokens", 0) or 0,
                cache_read_input_tokens=getattr(details, "cached_tokens", 0) or 0 if details else 0,
            )
        return ChatResponse(
            message=Message(role=Role.ASSISTANT, content=blocks),
            stop_reason=finish,
            usage=usage,
            model=resp.model or self.model,
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
            "messages": self._to_api_messages(messages, system),
        }
        if tools:
            params["tools"] = self._to_api_tools(tools)
        eff_temp = temperature if temperature is not None else self.temperature
        if eff_temp is not None:
            params["temperature"] = eff_temp
        params.update(kwargs)
        try:
            resp = await self._client.chat.completions.create(**params)
        except Exception as e:  # noqa: BLE001
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
            "messages": self._to_api_messages(messages, system),
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        if tools:
            params["tools"] = self._to_api_tools(tools)
        eff_temp = temperature if temperature is not None else self.temperature
        if eff_temp is not None:
            params["temperature"] = eff_temp
        params.update(kwargs)

        text_parts: List[str] = []
        tool_calls: Dict[int, Dict[str, str]] = {}  # index → {id, name, arguments}
        usage = Usage()
        finish_reason: Optional[str] = None
        model_name = self.model

        try:
            stream = await self._client.chat.completions.create(**params)
            async for chunk in stream:
                if chunk.usage:
                    details = getattr(chunk.usage, "prompt_tokens_details", None)
                    usage = Usage(
                        input_tokens=chunk.usage.prompt_tokens or 0,
                        output_tokens=chunk.usage.completion_tokens or 0,
                        cache_read_input_tokens=getattr(details, "cached_tokens", 0) or 0 if details else 0,
                    )
                for choice in chunk.choices or []:
                    if choice.finish_reason:
                        finish_reason = choice.finish_reason
                    delta = choice.delta
                    if not delta:
                        continue
                    if delta.content:
                        text_parts.append(delta.content)
                        yield StreamEvent("text_delta", text=delta.content)
                    for tc in delta.tool_calls or []:
                        entry = tool_calls.setdefault(tc.index, {"id": "", "name": "", "arguments": ""})
                        if tc.id:
                            entry["id"] = tc.id
                        if tc.function:
                            if tc.function.name:
                                entry["name"] += tc.function.name
                            if tc.function.arguments:
                                entry["arguments"] += tc.function.arguments
                if getattr(chunk, "model", None):
                    model_name = chunk.model
        except Exception as e:  # noqa: BLE001
            raise _translate_error(e) from e

        blocks: List[Any] = []
        if text_parts:
            blocks.append(TextBlock(text="".join(text_parts)))
        for idx in sorted(tool_calls):
            entry = tool_calls[idx]
            try:
                args = json.loads(entry["arguments"]) if entry["arguments"] else {}
            except json.JSONDecodeError:
                args = {"_raw": entry["arguments"]}
            blocks.append(ToolUseBlock(id=entry["id"], name=entry["name"], input=args))

        stop = StopReason.TOOL_USE if tool_calls else _FINISH_MAP.get(finish_reason, StopReason.OTHER)
        yield StreamEvent(
            "message",
            response=ChatResponse(
                message=Message(role=Role.ASSISTANT, content=blocks),
                stop_reason=stop,
                usage=usage,
                model=model_name,
            ),
        )

    async def count_tokens(self, messages: List[Message]) -> int:
        total = 0
        for m in messages:
            for b in m.blocks():
                if isinstance(b, ToolUseBlock):
                    total += len(b.name) + len(json.dumps(b.input, ensure_ascii=False))
                else:
                    total += len(str(getattr(b, "text", "") or getattr(b, "content", "") or ""))
        return total // 4
