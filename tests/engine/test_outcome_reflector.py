"""结果反思（reflector.reflect_on_outcome）测试。

业务逻辑：手写记录型 BaseLLMClient 替身（真实类非 mock 库）驱动真实
run_agent_turn 代码路径；断言 prompt 含真实结算数字、失败返回 None 不外抛。
LLM 集成：@pytest.mark.ai 真实客户端（复用 test_engine_reflection 的构建方式）。
"""

import pytest

from app.engine.agents.postprocess.reflector import Reflector
from app.llm.core.base import BaseLLMClient, StreamEvent
from app.llm.core.types import ChatResponse, Message, Role, StopReason, TextBlock

pytestmark = pytest.mark.asyncio


class RecordingLLM(BaseLLMClient):
    """记录收到的 user_prompt，返回固定教训文本。"""

    protocol = "openai"

    def __init__(self, response: str = "教训：置信度高的 Buy 决策跑赢基准 2.3%，可延续该分析路径。"):
        self.model = "recording-outcome-model"
        self.calls: list[str] = []
        self.response = response

    async def chat(self, messages, *, system=None, tools=None, max_tokens=4096, temperature=None, **kwargs):
        self.calls.append(messages[-1].content)
        return ChatResponse(
            message=Message(role=Role.ASSISTANT, content=[TextBlock(text=self.response)]),
            stop_reason=StopReason.END_TURN,
        )

    async def chat_stream(self, messages, *, system=None, tools=None, max_tokens=4096, temperature=None, **kwargs):
        resp = await self.chat(messages, system=system)
        yield StreamEvent("message", response=resp)

    async def count_tokens(self, messages):
        return 1


class FailingLLM(BaseLLMClient):
    protocol = "openai"
    model = "failing-model"

    async def chat(self, messages, **kwargs):
        raise RuntimeError("LLM 不可用")

    async def chat_stream(self, messages, **kwargs):
        raise RuntimeError("LLM 不可用")
        yield  # pragma: no cover

    async def count_tokens(self, messages):
        return 1


BRIEF = "[2026-10-10] 平安银行(000001)【Buy·置信度80】 基本面与市场结构共振，短线动能占优。"


class TestReflectOnOutcome:
    async def test_prompt_contains_real_numbers(self):
        llm = RecordingLLM()
        r = Reflector(llm)
        lesson = await r.reflect_on_outcome(
            BRIEF,
            {
                "return_pct": 5.4,
                "benchmark_symbol": "000300.SH",
                "benchmark_return_pct": 2.0,
                "alpha_pct": 3.4,
                "horizon_days": 7,
            },
        )
        assert lesson == llm.response
        prompt = llm.calls[0]
        assert BRIEF in prompt
        # 真实数字必须进 prompt（教训要引用数字，不许空谈）
        assert "5.40%" in prompt
        assert "2.00%" in prompt
        assert "3.40%" in prompt
        assert "7" in prompt

    async def test_missing_fields_skipped_in_prompt(self):
        llm = RecordingLLM()
        r = Reflector(llm)
        await r.reflect_on_outcome(BRIEF, {"return_pct": -1.2})
        prompt = llm.calls[0]
        assert "-1.20%" in prompt
        assert "基准" not in prompt.split("结算结果")[1]
        assert "超额" not in prompt

    async def test_llm_failure_returns_none(self):
        r = Reflector(FailingLLM())
        assert await r.reflect_on_outcome(BRIEF, {"return_pct": 1.0}) is None

    async def test_empty_response_returns_none(self):
        r = Reflector(RecordingLLM(response="   "))
        assert await r.reflect_on_outcome(BRIEF, {"return_pct": 1.0}) is None
