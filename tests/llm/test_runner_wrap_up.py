"""轮数将尽时的收尾催促与降级回退守卫。

实盘现象：某分析师连续 12 轮只调工具、从未提交，被 runner 硬停后报告退化为占位文本
（且占位文案误写为「LLM 返回空响应」，把排查方向带偏）。本测试锁定三件事：

1. 最后一轮注入收尾催促（且仅一次），且只在预算 >= 3 轮时启用；
2. 小额预算与正常收尾路径不受影响（避免挤占首轮工作）；
3. 占位文案按真实原因区分（轮数耗尽 ≠ 模型空响应）。
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.llm.core.base import BaseLLMClient, StreamEvent
from app.llm.core.types import (
    ChatResponse,
    Message,
    Role,
    StopReason,
    TextBlock,
    ToolDef,
    ToolUseBlock,
)
from app.llm.runner import (
    SUBMIT_REQUIRED_INSTRUCTION,
    WRAP_UP_INSTRUCTION,
    run_conversation,
)

AGENTS_PATH = Path(__file__).resolve().parents[2] / "app" / "engine" / "orchestrator" / "agents.py"


def _chat_response(blocks, stop_reason=StopReason.END_TURN) -> ChatResponse:
    return ChatResponse(message=Message(role=Role.ASSISTANT, content=blocks), stop_reason=stop_reason)


class _ScriptedLLM(BaseLLMClient):
    """按脚本逐轮返回：最多一次文本轮，其余轮返回工具调用。"""

    protocol = "openai"

    def __init__(
        self,
        *,
        text_on_turn: int | None = None,
        finish_on_turn: int | None = None,
        text: str = "阶段性结论：数据已足够",
        submit_on_turn: int | None = None,
    ):
        self.model = "scripted-model"
        self.text_on_turn = text_on_turn
        self.finish_on_turn = finish_on_turn
        self.submit_on_turn = submit_on_turn
        self.text = text
        self.seen_messages: list = []
        self.turn = 0  # 真实轮次计数（不能用消息条数：每轮会追加多条消息）
        self.last_tools = None  # 最近一次请求携带的工具集（验「只留提交工具」补救）

    async def chat(self, messages, *, system=None, **kwargs) -> ChatResponse:
        self.seen_messages = list(messages)
        self.turn += 1
        turn = self.turn
        if self.finish_on_turn is not None and turn == self.finish_on_turn:
            # 只回文本 → 循环正常收尾
            return _chat_response([TextBlock(text=self.text)])
        # 提交轮调用提交工具；提交之后的轮次以文本收尾（模拟"先提交、再结束"的正常路径）
        if self.submit_on_turn is not None and turn > self.submit_on_turn:
            return _chat_response([TextBlock(text=self.text)])
        blocks = []
        if self.text_on_turn is not None and turn == self.text_on_turn:
            # 文本 + 工具调用同行 → 循环继续（用于验证"最后一轮被迫停止时仍有正文可回退"）
            blocks.append(TextBlock(text=self.text))
        tool = "submit_report" if turn == self.submit_on_turn else "noop"
        blocks.append(ToolUseBlock(id=f"call_{turn}", name=tool, input={"n": turn}))
        return _chat_response(blocks, stop_reason=StopReason.TOOL_USE)

    async def chat_stream(self, messages, *, system=None, **kwargs):
        self.last_tools = kwargs.get("tools")
        yield StreamEvent("message", response=await self.chat(messages, system=system))

    async def count_tokens(self, messages) -> int:
        return 1


def _noop_tool() -> list[ToolDef]:
    async def handler(**kwargs):
        return "ok"

    return [ToolDef(name="noop", description="noop", params_schema={}, handler=handler)]


def _nudge_count(messages) -> int:
    n = 0
    for m in messages:
        content = m.content if isinstance(m.content, str) else ""
        if WRAP_UP_INSTRUCTION in content:
            n += 1
    return n


class TestWrapUpNudge:
    @pytest.mark.asyncio
    async def test_small_budget_does_not_inject_nudge(self):
        """1~2 轮预算没有回旋余地，催促只会挤占首轮工作，因此不注入。"""
        result = await run_conversation(
            _ScriptedLLM(), "开始分析", tools=_noop_tool(), max_turns=2
        )
        assert result.stop_reason == "max_turns"
        assert _nudge_count(result.messages) == 0

    @pytest.mark.asyncio
    async def test_last_turn_injects_wrap_up_nudge_once(self):
        result = await run_conversation(
            _ScriptedLLM(), "开始分析", tools=_noop_tool(), max_turns=3
        )
        assert result.stop_reason == "max_turns"
        assert _nudge_count(result.messages) == 1, "最后一轮必须注入且只注入一次收尾催促"

    @pytest.mark.asyncio
    async def test_nudge_not_injected_when_agent_submits_and_finishes(self):
        """正常收尾（先 submit_report、再给文本）不得注入任何催促，避免打断既有节奏。"""
        llm = _ScriptedLLM(submit_on_turn=2, finish_on_turn=3)
        result = await run_conversation(
            llm, "开始分析", tools=_tools_with_submit(), max_turns=5
        )
        assert result.stop_reason != "max_turns", "已提交的正常收尾不该被强停"
        assert _nudge_count(result.messages) == 0
        assert _submit_nudge_count(result.messages) == 0, "已提交过就不该再要提交"

    @pytest.mark.asyncio
    async def test_submit_gate_fires_when_text_ends_without_submitting(self):
        """给文本收尾却从未提交 → 未提交闸门必须催提交，且不得因此无限循环。"""
        llm = _ScriptedLLM(finish_on_turn=2)
        result = await run_conversation(
            llm, "开始分析", tools=_tools_with_submit(), max_turns=5
        )
        assert _submit_nudge_count(result.messages) >= 1, "未提交就收尾 → 必须催提交"
        assert llm.turn <= 7, "催促不得导致无限循环（5 轮预算 + 补救 1 轮的上界）"

class TestPlaceholderTruthfulness:
    """占位文案必须反映真实原因（否则会误导排查方向）。"""

    def _source(self) -> str:
        return AGENTS_PATH.read_text(encoding="utf-8")

    def test_max_turns_has_distinct_placeholder(self):
        source = self._source()
        block = source[source.index("final_report = submission.content.strip()") :][:600]
        assert 'result.stop_reason == "max_turns"' in block, "应按停止原因区分占位文案"
        assert "已达最大工具轮数" in block, "轮数耗尽的占位文案需说明真实原因"

    def test_empty_response_placeholder_retained(self):
        block = self._source()
        block = block[block.index("final_report = submission.content.strip()") :][:600]
        assert "LLM 返回空响应" in block, "模型确实返回空内容的分支需保留"

    def test_placeholder_mentions_configured_limit(self):
        block = self._source()
        block = block[block.index("final_report = submission.content.strip()") :][:600]
        assert re.search(r"max_tool_calls", block), "占位文案应带上实际轮数上限，便于定位"


def _submit_nudge_count(messages) -> int:
    return sum(
        1
        for m in messages
        if isinstance(m.content, str) and SUBMIT_REQUIRED_INSTRUCTION in m.content
    )


def _tools_with_submit() -> list[ToolDef]:
    async def handler(**kwargs):
        return "ok"

    return _noop_tool() + [
        ToolDef(
            name="submit_report",
            description="提交报告",
            params_schema={},
            handler=handler,
        )
    ]


class TestHardStopSalvage:
    """硬停补救：调工具调到轮数耗尽、且整个会话从未提交 → 收窄为仅提交工具再补 1 轮。

    实盘现象：某分析师 12 轮全在调工具、一次 submit_report 都没调 → 被强停成占位报告。
    补救必须在**被强停之前**换掉工具集：只在超轮后 `continue` 的话，补救轮永远不被调用。
    """

    @pytest.mark.asyncio
    async def test_salvage_retries_once_with_submit_tool_only(self):
        llm = _ScriptedLLM()  # 无收尾轮 → 每轮都只发 noop 工具调用，从不提交
        result = await run_conversation(
            llm, "开始分析", tools=_tools_with_submit(), max_turns=3
        )
        assert llm.turn == 4, "轮数耗尽后应额外跑 1 轮补救（3 轮预算 + 1 轮）"
        assert _submit_nudge_count(result.messages) == 1, "应注入恰一次强制提交请求"
        names = {t.name for t in (llm.last_tools or [])}
        assert names == {"submit_report"}, f"补救轮的工具应只剩提交工具，实际 {names}"
        assert result.stop_reason == "max_turns", "仍未提交时停止原因应保持 max_turns"

    @pytest.mark.asyncio
    async def test_no_salvage_on_small_budget(self):
        llm = _ScriptedLLM()
        result = await run_conversation(
            llm, "开始分析", tools=_tools_with_submit(), max_turns=2
        )
        assert llm.turn == 2, "小额预算（<3 轮）不得启用补救，避免挤占首轮工作"
        assert _submit_nudge_count(result.messages) == 0
