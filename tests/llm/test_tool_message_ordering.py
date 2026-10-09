"""tool 消息顺序约束的守卫测试。

OpenAI 协议要求每个 `assistant.tool_calls` 之后**紧邻**应答它的 `tool` 消息：

    An assistant message with 'tool_calls' must be followed by tool messages
    responding to each tool_call_id

历史里的典型形态是 `assistant(tool_calls) → user(tool_result) → assistant(文本)`：
工具结果挂在 user 消息上、需要重排产出，而 assistant 文本若先落盘就会插进
tool_calls 与其结果之间，导致整轮请求被拒。本测试锁定该顺序不被破坏。
"""

from __future__ import annotations

from app.llm.core.types import (
    Message,
    Role,
    TextBlock,
    ToolResultBlock,
    ToolUseBlock,
)
from app.llm.protocols.openai_client import OpenAILLMClient


def _client() -> OpenAILLMClient:
    return OpenAILLMClient(api_key="test-key", base_url="http://127.0.0.1:9/v1", model="m")


def _assert_tool_order(out):
    """每个 assistant.tool_calls 的 id 都必须被紧随其后的 tool 消息应答。"""
    pending: set = set()
    for m in out:
        if m["role"] == "tool":
            assert m.get("tool_call_id") in pending, f"tool 消息无对应 tool_call: {m}"
            pending.discard(m["tool_call_id"])
        else:
            assert not pending, f"tool_calls 之后未紧跟 tool 消息，缺 {pending}"
            if m["role"] == "assistant":
                pending = {c["id"] for c in (m.get("tool_calls") or [])}
    assert not pending, f"结尾仍有未应答的 tool_calls: {pending}"


def test_assistant_text_after_tool_loop_does_not_break_ordering():
    """工具循环后模型直接给结论（最常见形态）时，tool 结果不得被挤到最后。"""
    hist = [
        Message(role=Role.USER, content="查一下"),
        Message(role=Role.ASSISTANT, content=[ToolUseBlock(id="c1", name="t1", input={})]),
        Message(role=Role.USER, content=[ToolResultBlock(tool_use_id="c1", content="v1")]),
        Message(role=Role.ASSISTANT, content=[TextBlock(text="结论")]),
    ]
    out = _client()._to_api_messages(hist, None)
    assert [m["role"] for m in out] == ["user", "assistant", "tool", "assistant"], out
    _assert_tool_order(out)


def test_multi_round_tool_loop_keeps_each_call_answered():
    hist = [
        Message(role=Role.USER, content="开始"),
        Message(role=Role.ASSISTANT, content=[ToolUseBlock(id="c1", name="t1", input={})]),
        Message(role=Role.USER, content=[ToolResultBlock(tool_use_id="c1", content="v1")]),
        Message(role=Role.ASSISTANT, content=[ToolUseBlock(id="c2", name="t2", input={})]),
        Message(role=Role.USER, content=[ToolResultBlock(tool_use_id="c2", content="v2")]),
        Message(role=Role.ASSISTANT, content=[TextBlock(text="结论")]),
    ]
    out = _client()._to_api_messages(hist, None)
    _assert_tool_order(out)


def test_user_text_message_still_flushes_before_text():
    """回归：user 文本分支原有的冲刷行为不得被破坏。"""
    hist = [
        Message(role=Role.USER, content="开始"),
        Message(role=Role.ASSISTANT, content=[ToolUseBlock(id="c1", name="t1", input={})]),
        Message(
            role=Role.USER,
            content=[ToolResultBlock(tool_use_id="c1", content="v1"), TextBlock(text="继续")],
        ),
    ]
    out = _client()._to_api_messages(hist, None)
    assert [m["role"] for m in out] == ["user", "assistant", "tool", "user"], out
    _assert_tool_order(out)
