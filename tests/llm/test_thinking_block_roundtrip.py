"""思考模型推理内容（ThinkingBlock）跨协议回传的守卫测试。

背景：OpenAI 兼容的思考模型（DeepSeek / vLLM / Qwen 等）在**带 tools** 的请求下
要求历史里所有 assistant 消息的推理内容原样回传，缺字段会被 API 以 400 拒绝：

    The `reasoning_content` in the thinking mode must be passed back to the API

canonical 层用 ThinkingBlock 承载推理内容（两个协议共用块类型），本测试锁定：

1. 响应解析：推理内容落到 ThinkingBlock（流式 / 非流式两条路径）；
2. 请求序列化：ThinkingBlock 折算成所属 assistant 消息的 reasoning_content，
   且不产出独立消息；
3. 思考模式下 assistant 消息必带该字段（空串合法），非思考模式不引入新字段。

测试全部基于真实对象（不 mock OpenAILLMClient 本身），模型调用被完全避开。
"""

from __future__ import annotations

from types import SimpleNamespace

from app.llm.core.types import (
    Message,
    Role,
    TextBlock,
    ThinkingBlock,
    ToolResultBlock,
    ToolUseBlock,
)
from app.llm.protocols.openai_client import OpenAILLMClient


def _client(thinking: bool = True) -> OpenAILLMClient:
    """构造客户端：思考模式由 thinking_effort 开启，不发起任何网络请求。"""
    return OpenAILLMClient(
        api_key="test-key",
        base_url="http://127.0.0.1:9/v1",
        model="deepseek-flash",
        thinking_effort="medium" if thinking else None,
    )


def _fake_response(content: str = "", reasoning: str = "", tool_calls=None):
    msg = SimpleNamespace(content=content, reasoning_content=reasoning, tool_calls=tool_calls)
    choice = SimpleNamespace(message=msg, finish_reason="tool_calls" if tool_calls else "stop")
    usage = SimpleNamespace(prompt_tokens=10, completion_tokens=5, prompt_tokens_details=None)
    return SimpleNamespace(choices=[choice], usage=usage, model="deepseek-flash")


# ── 1. 响应解析：推理内容落到 ThinkingBlock ────────────────────────────


class TestCapture:
    def test_non_stream_reasoning_becomes_thinking_block(self):
        resp = _client()._response_to_canonical(_fake_response(content="结论", reasoning="我先看数据"))
        blocks = resp.message.blocks()
        assert any(isinstance(b, ThinkingBlock) for b in blocks), blocks
        tb = next(b for b in blocks if isinstance(b, ThinkingBlock))
        assert tb.thinking == "我先看数据"
        # 原有文本块不受影响
        assert any(isinstance(b, TextBlock) and b.text == "结论" for b in blocks)

    def test_non_stream_without_reasoning_adds_no_block(self):
        resp = _client()._response_to_canonical(_fake_response(content="结论"))
        assert not any(isinstance(b, ThinkingBlock) for b in resp.message.blocks())

    def test_non_stream_accepts_reasoning_alias(self):
        """部分网关用 reasoning 而非 reasoning_content。"""
        msg = SimpleNamespace(content="", reasoning="别的键名", reasoning_content=None, tool_calls=None)
        resp = _client()._response_to_canonical(
            SimpleNamespace(
                choices=[SimpleNamespace(message=msg, finish_reason="stop")],
                usage=None,
                model="m",
            )
        )
        tb = next(b for b in resp.message.blocks() if isinstance(b, ThinkingBlock))
        assert tb.thinking == "别的键名"


# ── 2. 请求序列化：折算成 assistant 的 reasoning_content ──────────────


class TestSerialization:
    def test_thinking_block_does_not_become_its_own_message(self):
        hist = [
            Message(role=Role.USER, content="开始"),
            Message(
                role=Role.ASSISTANT,
                content=[ThinkingBlock(thinking="推理"), TextBlock(text="结论")],
            ),
        ]
        out = _client()._to_api_messages(hist, None)
        assert [m["role"] for m in out] == ["user", "assistant"], out
        assert out[1]["content"] == "结论"
        assert out[1]["reasoning_content"] == "推理"

    def test_reasoning_attached_to_tool_calls_message(self):
        """含 tool_calls 的 assistant 消息必须带上推理内容（否则 API 400）。"""
        hist = [
            Message(role=Role.USER, content="查一下"),
            Message(
                role=Role.ASSISTANT,
                content=[ThinkingBlock(thinking="该调工具"), ToolUseBlock(id="c1", name="quote", input={})],
            ),
        ]
        out = _client()._to_api_messages(hist, None)
        assistant = next(m for m in out if m["role"] == "assistant")
        assert assistant["tool_calls"][0]["id"] == "c1"
        assert assistant["reasoning_content"] == "该调工具"

    def test_thinking_mode_always_sends_field_even_when_empty(self):
        """思考模式下，历史里没有推理内容的 assistant 消息也要带空串（合法值）。"""
        hist = [
            Message(role=Role.USER, content="hi"),
            Message(role=Role.ASSISTANT, content="hello"),
        ]
        out = _client(thinking=True)._to_api_messages(hist, None)
        assert out[1]["reasoning_content"] == ""

    def test_non_thinking_client_does_not_inject_field(self):
        """非思考模型不应凭空多出 reasoning_content（避免污染无关请求）。"""
        hist = [
            Message(role=Role.USER, content="hi"),
            Message(role=Role.ASSISTANT, content="hello"),
        ]
        out = _client(thinking=False)._to_api_messages(hist, None)
        assert "reasoning_content" not in out[1]

    def test_user_message_is_never_given_reasoning(self):
        hist = [Message(role=Role.USER, content=[TextBlock(text="用户文本")])]
        out = _client()._to_api_messages(hist, None)
        assert "reasoning_content" not in out[0]


# ── 3. 思考模式下的推理完整性 ────────────────────────────────────────


class TestThinkingModeCompleteness:
    def test_all_assistant_messages_carry_reasoning_in_thinking_mode(self):
        """回归：思考模式下只要有一条 assistant 漏字段，API 就整体 400。"""
        hist = [
            Message(role=Role.USER, content="开始"),
            Message(role=Role.ASSISTANT, content=[ToolUseBlock(id="c1", name="t1", input={})]),
            Message(role=Role.USER, content=[ToolResultBlock(tool_use_id="c1", content="v1")]),
            Message(role=Role.ASSISTANT, content=[TextBlock(text="结论")]),
        ]
        out = _client(thinking=True)._to_api_messages(hist, None)
        for m in out:
            if m["role"] == "assistant":
                assert "reasoning_content" in m, m
