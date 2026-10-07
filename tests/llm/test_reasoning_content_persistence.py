"""reasoning_content 在多轮工具循环中的保全（回归测试）。

背景（DeepSeek 官方 thinking_mode 文档原文）：
    "for requests carrying the `tools` parameter, the `reasoning_content` must be fully
     passed back to the API in all subsequent requests — even for turns where the model
     did not perform a tool call. If your code does not correctly pass back
     `reasoning_content`, the API will return a 400 error."

本机故障：分析任务（带 270 个工具的 A 股分析师）报
    400 The `reasoning_content` in the thinking mode must be passed back to the API.
根因有两处把 CoT 静默丢弃，外加一处「该带字段却没带」：
  1. compact/auto_compactor._microcompact —— 重建消息时只带 role/content
  2. tools/pairing.ensure_pairing —— 重建 user 消息时同样丢字段
  3. protocols/openai_client._to_api_messages —— 只在 reasoning 非空时写入字段，
     思考模式下缺字段即 400
"""

from app.llm.compact.auto_compactor import AutoCompactor, CompactConfig
from app.llm.compact.token_counter import TokenCounter
from app.llm.core.types import (
    Message,
    Role,
    TextBlock,
    ToolResultBlock,
    ToolUseBlock,
)
from app.llm.protocols.openai_client import OpenAILLMClient
from app.llm.tools.pairing import ensure_pairing

# 占位符长度以下的 tool_result 不会被 microcompact 替换，用长文本保证触发
LONG = "结果" * 800


def _client(thinking: bool) -> OpenAILLMClient:
    """真实客户端对象（不发请求；thinking 开关决定是否注入思考参数）。"""
    return OpenAILLMClient(
        api_key="sk-unit-test-not-used",
        base_url="https://example.invalid",
        model="deepseek-v4-flash",
        thinking_effort="high" if thinking else None,
    )


def _history_with_tools(rounds: int = 3) -> list:
    msgs = [Message(role=Role.USER, content="开始")]
    for i in range(rounds):
        msgs.append(
            Message(
                role=Role.ASSISTANT,
                content=[ToolUseBlock(id=f"c{i}", name="get_date", input={})],
                reasoning_content=f"第{i}轮思考：先拿日期。",
            )
        )
        msgs.append(
            Message(role=Role.USER, content=[ToolResultBlock(tool_use_id=f"c{i}", content=LONG)])
        )
    msgs.append(Message(role=Role.ASSISTANT, content=[TextBlock(text="结论")], reasoning_content="收尾思考"))
    return msgs


# ── 1) microcompact 必须保住 CoT ────────────────────────────


def test_microcompact_preserves_reasoning_content():
    hist = _history_with_tools()
    before = {id(m): (getattr(m, "reasoning_content", "") or "") for m in hist}

    comp = AutoCompactor(_client(True), TokenCounter(), CompactConfig(keep_recent_turns=1, min_tool_results_to_clear=1))
    out = comp._microcompact(hist)

    assert out is not hist, "microcompact 未生效，测试前提不成立（需更多长 tool_result）"
    for m in out:
        if m.role == Role.ASSISTANT:
            assert (getattr(m, "reasoning_content", "") or ""), f"assistant 的 CoT 被丢弃: {m.content!r}"
    # 内容本身也应保持（只有 tool_result 被替换）
    assert any("第0轮思考" in (getattr(m, "reasoning_content", "") or "") for m in out if m.role == Role.ASSISTANT)


def test_microcompact_keeps_tool_use_blocks():
    hist = _history_with_tools()
    comp = AutoCompactor(_client(True), TokenCounter(), CompactConfig(keep_recent_turns=1, min_tool_results_to_clear=1))
    out = comp._microcompact(hist)
    assert out is not hist
    ids = [b.id for m in out for b in m.blocks() if isinstance(b, ToolUseBlock)]
    assert ids == ["c0", "c1", "c2"], f"tool_use 块丢失或顺序变化: {ids}"


# ── 2) pairing 修复也要保住 CoT ─────────────────────────────


def test_pairing_preserves_reasoning_content():
    hist = [
        Message(role=Role.USER, content="开始"),
        Message(
            role=Role.ASSISTANT,
            content=[ToolUseBlock(id="c0", name="get_date", input={})],
            reasoning_content="需要日期",
        ),
        # 孤儿 tool_result：没有对应的 tool_use → pairing 会重建这条 user 消息
        Message(role=Role.USER, content=[ToolResultBlock(tool_use_id="ghost", content="x")]),
        Message(role=Role.USER, content=[TextBlock(text="继续")]),
    ]
    out = ensure_pairing(hist)
    assert out is not hist, "pairing 未触发，测试前提不成立"
    assistant = [m for m in out if m.role == Role.ASSISTANT]
    assert assistant and (assistant[0].reasoning_content or "") == "需要日期"


# ── 3) 转换层：思考模式下所有 assistant 都带字段；非思考模式不带 ──


def test_thinking_client_always_emits_reasoning_field():
    client = _client(True)
    hist = [
        Message(role=Role.ASSISTANT, content=[TextBlock(text="A")], reasoning_content="有思考"),
        Message(role=Role.ASSISTANT, content=[TextBlock(text="B")]),  # CoT 丢失的消息
        Message(role=Role.ASSISTANT, content=[ToolUseBlock(id="c", name="t", input={})]),  # 工具调用
    ]
    out = client._to_api_messages(hist, None)
    asst = [m for m in out if m.get("role") == "assistant"]
    assert len(asst) == 3
    for m in asst:
        assert "reasoning_content" in m, f"缺字段: {m}"
    assert asst[0]["reasoning_content"] == "有思考"
    assert asst[1]["reasoning_content"] == ""
    assert asst[2]["reasoning_content"] == ""


def test_non_thinking_client_omits_reasoning_field():
    client = _client(False)
    hist = [Message(role=Role.ASSISTANT, content=[TextBlock(text="A")])]
    out = client._to_api_messages(hist, None)
    assert "reasoning_content" not in out[0], "非思考模型不应注入未知字段（避免别的网关 400）"


def test_non_empty_reasoning_always_emitted_even_on_non_thinking_client():
    client = _client(False)
    hist = [Message(role=Role.ASSISTANT, content=[TextBlock(text="A")], reasoning_content="X")]
    out = client._to_api_messages(hist, None)
    assert out[0]["reasoning_content"] == "X"


# ── 4) 顺序：role:"tool" 必须紧跟自己的 assistant.tool_calls ──


def test_tool_messages_follow_their_tool_calls():
    """多轮工具循环下不得把所有 tool 消息挤到对话末尾（否则 API 400）。"""
    client = _client(True)
    hist = [
        Message(role=Role.USER, content="开始"),
        Message(role=Role.ASSISTANT, content=[ToolUseBlock(id="c0", name="t0", input={})], reasoning_content="r0"),
        Message(role=Role.USER, content=[ToolResultBlock(tool_use_id="c0", content="v0")]),
        Message(role=Role.ASSISTANT, content=[ToolUseBlock(id="c1", name="t1", input={})], reasoning_content="r1"),
        Message(role=Role.USER, content=[ToolResultBlock(tool_use_id="c1", content="v1")]),
        Message(role=Role.ASSISTANT, content=[TextBlock(text="结论")], reasoning_content="r2"),
        Message(role=Role.USER, content="谢谢"),
    ]
    out = client._to_api_messages(hist, None)
    roles = [m["role"] for m in out]
    for i, m in enumerate(out):
        if m.get("tool_calls"):
            ids = [t["id"] for t in m["tool_calls"]]
            nxt = out[i + 1]
            assert nxt["role"] == "tool" and nxt["tool_call_id"] == ids[0], (i, ids, nxt)


def test_tool_result_and_user_text_in_same_message_keeps_tool_first():
    """一条 canonical user 消息同时含 tool_result 与文本时，tool 必须先于 user 文本。"""
    client = _client(True)
    hist = [
        Message(role=Role.ASSISTANT, content=[ToolUseBlock(id="c0", name="t0", input={})], reasoning_content="r"),
        Message(
            role=Role.USER,
            content=[ToolResultBlock(tool_use_id="c0", content="v0"), TextBlock(text="继续")],
        ),
    ]
    out = client._to_api_messages(hist, None)
    assert [m["role"] for m in out] == ["assistant", "tool", "user"], [m["role"] for m in out]
