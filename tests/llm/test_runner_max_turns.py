"""runner max_turns 兜底收敛测试（手写记录型 BaseLLMClient 替身，非 mock 库）。

覆盖：工具循环耗尽（模型一直请求工具）→ final_text 为空 → 追加一次无工具
收敛调用抢救正文；收敛调用不携带 tools（杜绝二次工具循环）。
"""

import pytest

from app.llm import Message, Role, ToolUseBlock, run_conversation
from app.llm.core.base import BaseLLMClient, StreamEvent
from app.llm.core.types import ChatResponse, StopReason, TextBlock
from app.llm.tools.registry import ToolRegistry

pytestmark = pytest.mark.asyncio


class ToolLoopThenAnswerLLM(BaseLLMClient):
    """有工具就一直调用工具（永不自然停止）；无 tools 时返回正文。

    calls 记录每次 chat_stream 收到的 tools 实参，供断言收敛调用不携带工具。
    """

    protocol = "openai"

    def __init__(self):
        self.model = "fake-tool-loop-model"
        self.calls = []

    async def chat_stream(self, messages, *, system=None, tools=None, max_tokens=4096, temperature=None, **kwargs):
        self.calls.append(tools)
        if tools:
            resp = ChatResponse(
                message=Message(
                    role=Role.ASSISTANT,
                    content=[ToolUseBlock(id=f"tu{len(self.calls)}", name="add_numbers", input={"a": 1, "b": 2})],
                ),
                stop_reason=StopReason.TOOL_USE,
            )
        else:
            resp = ChatResponse(
                message=Message(role=Role.ASSISTANT, content=[TextBlock(text="基于已有信息的收敛报告")]),
                stop_reason=StopReason.END_TURN,
            )
        yield StreamEvent("message", response=resp)

    async def chat(self, messages, *, system=None, tools=None, max_tokens=4096, temperature=None, **kwargs):
        if tools:
            resp = ChatResponse(
                message=Message(
                    role=Role.ASSISTANT,
                    content=[ToolUseBlock(id="tu-x", name="add_numbers", input={"a": 1, "b": 2})],
                ),
                stop_reason=StopReason.TOOL_USE,
            )
        else:
            resp = ChatResponse(
                message=Message(role=Role.ASSISTANT, content=[TextBlock(text="基于已有信息的收敛报告")]),
                stop_reason=StopReason.END_TURN,
            )
        return resp

    async def count_tokens(self, messages):
        return 1


@pytest.fixture
def registry() -> ToolRegistry:
    reg = ToolRegistry()

    @reg.register(
        description="计算两个整数的和。",
        params_schema={
            "type": "object",
            "properties": {"a": {"type": "integer"}, "b": {"type": "integer"}},
            "required": ["a", "b"],
        },
    )
    def add_numbers(a: int, b: int) -> str:
        return str(a + b)

    return reg


async def test_max_turns_salvages_final_text(registry):
    """工具循环耗尽：一次无工具收敛调用抢救出正文，stop_reason 保持 max_turns。"""
    llm = ToolLoopThenAnswerLLM()
    result = await run_conversation(
        llm,
        "请持续用工具计算，直到被要求停止。",
        system="你是计算助手。",
        registry=registry,
        tools=registry.defs(),
        max_turns=3,
    )
    assert result.stop_reason == "max_turns"
    assert result.tool_calls_executed >= 2
    assert result.salvaged_after_max_turns is True
    assert result.final_text == "基于已有信息的收敛报告"
    # 收敛调用（最后一次）不携带任何工具
    assert llm.calls[-1] is None
    # 收敛调用前发生过带工具的调用
    assert any(c is not None for c in llm.calls[:-1])
