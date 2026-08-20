"""后端事件增强测试（真实代码路径，禁止 mock）

覆盖：
- llm_request：首轮 messages 全量数组 + messages_full，后续轮次只带条数
- llm_response：text 字段（本轮 assistant 文本全文，纯工具轮为空串）
- thinking 事件：raw 响应含 thinking/reasoning 块时发射，且走落库通道
- tool_call / tool_result：tool_use_id 配对，output 截断 8000
- user_message_injected 的 system-reminder 解包（纯函数）
- pipeline report_ready：diff state.reports 新增/变化 key，title 解析链，content 截断
"""

from typing import Any, Dict, List

import pytest

from app.engine.orchestrator.pipeline import _emit_report_ready, _report_display_title
from app.llm import create_client
from app.llm.config import load_config
from app.llm.core.base import BaseLLMClient, StreamEvent
from app.llm.core.types import (
    ChatResponse,
    Message,
    Role,
    StopReason,
    TextBlock,
    ToolResultBlock,
    ToolUseBlock,
    Usage,
)
from app.llm.events import (
    REPORT_CONTENT_MAX_CHARS,
    TOOL_RESULT_MAX_CHARS,
    EventSink,
    flatten_message_content,
    messages_event_payload,
    unwrap_system_reminder,
)
from app.llm.runner import run_conversation
from app.llm.tools.registry import ToolRegistry


# ---------- 测试基础设施：手写脚本化客户端（真实类，非 mock 库） ----------


class _ThinkingBlock:
    """模拟 Anthropic SDK thinking content block（raw 响应中的形状）"""

    type = "thinking"

    def __init__(self, text: str):
        self.thinking = text


class _RawResponse:
    def __init__(self, content: List[Any]):
        self.content = content


class _ScriptedClient(BaseLLMClient):
    """按脚本顺序返回预设响应；记录收到的请求消息供断言"""

    protocol = "test"
    model = "test-model"

    def __init__(self, responses: List[ChatResponse]):
        self._responses = list(responses)
        self.requests: List[List[Message]] = []

    async def chat(self, messages, **kwargs) -> ChatResponse:
        return self._responses.pop(0)

    async def chat_stream(self, messages, **kwargs):
        self.requests.append(list(messages))
        resp = self._responses.pop(0)
        yield StreamEvent("message", response=resp)

    async def count_tokens(self, messages) -> int:
        return 16


def _resp(*blocks: Any, raw: Any = None) -> ChatResponse:
    return ChatResponse(
        message=Message(role=Role.ASSISTANT, content=list(blocks)),
        stop_reason=StopReason.TOOL_USE if any(isinstance(b, ToolUseBlock) for b in blocks) else StopReason.END_TURN,
        usage=Usage(input_tokens=10, output_tokens=5),
        model="test-model",
        raw=raw,
    )


def _capture_sink() -> tuple:
    events: List[Dict[str, Any]] = []
    persisted: List[Any] = []
    sink = EventSink(
        task_id="t-test",
        on_event=lambda ev: events.append(ev.to_dict()),
        on_persist=lambda batch: persisted.extend(batch),
        persist_batch=999,
    )
    return sink, events, persisted


def _echo_registry() -> ToolRegistry:
    reg = ToolRegistry()

    @reg.register(description="返回输入文本", params_schema={"type": "object", "properties": {"text": {"type": "string"}}})
    def echo(text: str = "") -> str:
        return text

    return reg


# ---------- llm_request / llm_response / tool_use_id（真实 run_conversation 路径） ----------


async def test_llm_request_messages_full_only_first_turn():
    """首轮带全量 messages 数组（含本轮 user 消息原文），后续轮次只带条数"""
    client = _ScriptedClient([
        _resp(TextBlock(text="先查一下"), ToolUseBlock(id="toolu_1", name="echo", input={"text": "hi"})),
        _resp(TextBlock(text="final answer")),
    ])
    sink, events, _persisted = _capture_sink()
    result = await run_conversation(
        client, "你好，请分析",
        registry=_echo_registry(), event_sink=sink,
        task_id="t-test", agent_key="market", phase="analysts",
    )
    assert result.final_text == "final answer"
    requests = [e for e in events if e["event_type"] == "llm_request"]
    assert len(requests) == 2

    first = requests[0]["payload"]
    assert first["messages_full"] is True
    assert isinstance(first["messages"], list)
    assert first["messages"][-1] == {"role": "user", "content": "你好，请分析"}
    assert all(set(m) == {"role", "content"} for m in first["messages"])

    second = requests[1]["payload"]
    assert second["messages_full"] is False
    # 第二次请求实际历史：user、assistant(text+tool_use)、user(tool_result) = 3 条
    assert second["messages"] == 3


async def test_llm_response_text_field():
    """llm_response.text 为本轮 assistant 文本全文；纯工具轮为空字符串但字段存在"""
    client = _ScriptedClient([
        _resp(ToolUseBlock(id="toolu_1", name="echo", input={"text": "x"})),
        _resp(TextBlock(text="part1"), TextBlock(text="part2")),
    ])
    sink, events, _ = _capture_sink()
    await run_conversation(client, "q", registry=_echo_registry(), event_sink=sink, agent_key="a")
    responses = [e["payload"] for e in events if e["event_type"] == "llm_response"]
    assert responses[0]["text"] == ""  # 纯工具轮
    assert responses[1]["text"] == "part1part2"  # 多 text block 拼接


async def test_tool_use_id_pairing_and_output_truncation():
    """tool_call 与 tool_result 的 tool_use_id 与 SDK 块 id 配对；output 截断 8000"""
    long_text = "x" * 10000

    reg = ToolRegistry()

    @reg.register(description="返回长文本", params_schema={"type": "object"})
    def long_tool() -> str:
        return long_text

    client = _ScriptedClient([
        _resp(ToolUseBlock(id="toolu_long", name="long_tool", input={})),
        _resp(TextBlock(text="done")),
    ])
    sink, events, _ = _capture_sink()
    await run_conversation(client, "q", registry=reg, event_sink=sink, agent_key="a")
    calls = [e["payload"] for e in events if e["event_type"] == "tool_call"]
    results = [e["payload"] for e in events if e["event_type"] == "tool_result"]
    assert calls[0]["tool_use_id"] == "toolu_long"
    assert results[0]["tool_use_id"] == "toolu_long"
    assert results[0]["tool"] == calls[0]["tool"] == "long_tool"
    assert len(results[0]["output"]) == TOOL_RESULT_MAX_CHARS == 8000


async def test_thinking_event_emitted_and_persisted():
    """raw 响应含 thinking 块时发射 thinking 事件，且进入落库缓冲（非 REALTIME_ONLY）"""
    raw = _RawResponse(content=[_ThinkingBlock("let me think..."), TextBlock(text="answer")])
    client = _ScriptedClient([_resp(TextBlock(text="answer"), raw=raw)])
    sink, events, persisted = _capture_sink()
    await run_conversation(client, "q", registry=_echo_registry(), event_sink=sink, agent_key="a")
    thinking = [e for e in events if e["event_type"] == "thinking"]
    assert len(thinking) == 1
    assert thinking[0]["payload"]["text"] == "let me think..."
    # text_delta 等不落库；thinking 不在排除清单 → flush 后进落库批次
    await sink.flush()
    persisted_types = [ev.event_type for ev in persisted]
    assert "thinking" in persisted_types
    assert "text_delta" not in persisted_types
    assert "llm_request" in persisted_types


async def test_full_messages_per_conversation_first_round():
    """全量 messages 按会话（run_conversation）首轮携带：
    同一 agent_key 的第二次会话（如辩论辩手的辩论轮）首轮重新携带全文，
    会话内后续轮次只带条数"""
    sink, events, _ = _capture_sink()
    # 会话 1：两轮（首轮 tool_use 续轮 + 收尾）→ 首轮全文、次轮条数
    client = _ScriptedClient([
        _resp(ToolUseBlock(id="t1", name="echo", input={"text": "x"})),
        _resp(TextBlock(text="ok")),
    ])
    await run_conversation(client, "q", registry=_echo_registry(), event_sink=sink, agent_key="same_agent")
    # 会话 2：同 agent_key 新会话 → 首轮重新携带全文（辩论轮对手报告可见）
    client2 = _ScriptedClient([_resp(TextBlock(text="ok"))])
    await run_conversation(client2, "q2", registry=_echo_registry(), event_sink=sink, agent_key="same_agent")
    requests = [e["payload"] for e in events if e["event_type"] == "llm_request"]
    assert requests[0]["messages_full"] is True
    assert isinstance(requests[0]["messages"], list)
    assert requests[1]["messages_full"] is False
    assert isinstance(requests[1]["messages"], int)
    assert requests[2]["messages_full"] is True
    assert isinstance(requests[2]["messages"], list)


# ---------- 纯函数：system-reminder 解包 / content 展平 ----------


def test_unwrap_system_reminder():
    wrapped = "<system-reminder>\n用户说：请加仓\n</system-reminder>"
    assert unwrap_system_reminder(wrapped) == "用户说：请加仓"
    assert unwrap_system_reminder("普通消息") == "普通消息"
    assert unwrap_system_reminder("") == ""
    # 非整条包裹（内嵌）不解包
    inline = "前文 <system-reminder>x</system-reminder> 后文"
    assert unwrap_system_reminder(inline) == inline


def test_flatten_message_content():
    assert flatten_message_content("plain") == "plain"
    assert flatten_message_content(None) == ""
    blocks = [
        TextBlock(text="hello "),
        ToolUseBlock(id="t1", name="echo", input={}),
        ToolResultBlock(tool_use_id="t1", content="result"),
    ]
    flattened = flatten_message_content(blocks)
    assert flattened.startswith("hello ")
    assert "[tool_use:echo]" in flattened
    assert "result" in flattened


def test_messages_event_payload_roles():
    msgs = [
        Message(role=Role.USER, content="q"),
        Message(role=Role.ASSISTANT, content=[TextBlock(text="a")]),
    ]
    payload = messages_event_payload(msgs)
    assert payload == [
        {"role": "user", "content": "q"},
        {"role": "assistant", "content": "a"},
    ]


# ---------- pipeline report_ready ----------


async def test_emit_report_ready_diff_and_payload():
    """新增/变化 key 发射、未变化 key 跳过；content 截断；title 解析链"""
    sink, events, _ = _capture_sink()
    before = {"unchanged_report": "same", "changed_report": "old"}
    update = {
        "reports": {
            "unchanged_report": "same",
            "changed_report": "new content",
            "fresh_report": "brand new",
        }
    }
    await _emit_report_ready(sink, update, agent_key="market", phase="analysts", before_reports=before)
    ready = [e for e in events if e["event_type"] == "report_ready"]
    assert [e["payload"]["report_key"] for e in ready] == ["changed_report", "fresh_report"]
    assert all(e["agent_key"] == "market" and e["phase"] == "analysts" for e in ready)
    assert ready[1]["payload"]["content"] == "brand new"


async def test_emit_report_ready_content_truncation():
    sink, events, _ = _capture_sink()
    long_report = "y" * (REPORT_CONTENT_MAX_CHARS + 1000)
    await _emit_report_ready(
        sink, {"reports": {"summary_report": long_report}},
        agent_key="summary", phase="summary", before_reports={},
    )
    ready = [e for e in events if e["event_type"] == "report_ready"]
    assert len(ready) == 1
    assert len(ready[0]["payload"]["content"]) == REPORT_CONTENT_MAX_CHARS


async def test_emit_report_ready_skips_non_dict_and_none_sink():
    """update 无 reports 或 event_sink 为 None 时安全跳过"""
    sink, events, _ = _capture_sink()
    await _emit_report_ready(sink, {"messages": []}, agent_key="a", phase="", before_reports={})
    await _emit_report_ready(None, {"reports": {"x_report": "y"}}, agent_key="a", phase="", before_reports={})
    assert not [e for e in events if e["event_type"] == "report_ready"]


def test_report_display_title_chain():
    """bull_researcher_report → slug bull-researcher → YAML 中文名（真实配置文件读取）"""
    title = _report_display_title("bull_researcher_report")
    assert title and title != "bull_researcher_report"  # 命中 YAML 中文名
    # display_name 回退
    assert _report_display_title("unknown_report_key", display_name="回退名") == "回退名"
    # 最终回退：report_key 原样
    assert _report_display_title("unknown_report_key") == "unknown_report_key"


@pytest.mark.parametrize("report_key", [
    "social_media_report",
    "short_term_capital_report",
    "fundamentals_report",
])
def test_report_display_title_stage1_analyst_suffix(report_key):
    """Stage 1 报告键不带 -analyst 后缀，但 YAML slug 带：应补试 <base>-analyst 命中中文名"""
    title = _report_display_title(report_key)
    assert title and title != report_key, f"{report_key} 应命中 YAML 中文名，实际: {title!r}"


@pytest.mark.parametrize("report_key", [
    "trader_investment_plan",
    "investment_plan",
    "research_team_decision",
    "risk_management_decision",
])
def test_report_display_title_slug_alias(report_key):
    """非派生命名的报告键经别名映射命中中文名（与前端 REPORT_KEY_SLUG_ALIAS 对齐）"""
    title = _report_display_title(report_key)
    assert title and title != report_key, f"{report_key} 应经别名命中中文名，实际: {title!r}"


@pytest.mark.ai
@pytest.mark.skipif(not load_config().api_key, reason="未配置 API key（.env ARK_API_KEY）")
async def test_enhanced_events_with_real_llm():
    """真实 LLM 端到端（需 API key；常规层跳过）"""
    client = create_client("anthropic")
    sink, events, _ = _capture_sink()
    result = await run_conversation(
        client, "用一句话说明什么是市盈率", registry=_echo_registry(),
        event_sink=sink, task_id="t-ai", agent_key="ai_test", phase="analysts",
    )
    assert result.final_text
    requests = [e["payload"] for e in events if e["event_type"] == "llm_request"]
    assert requests[0]["messages_full"] is True
    assert isinstance(requests[0]["messages"], list) and requests[0]["messages"][-1]["content"].startswith("用一句话")
