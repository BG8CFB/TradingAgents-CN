"""runner / invoker 的 token 用量记录钩子测试（unit）

用测试代码内实现的记录型 BaseLLMClient 子类与捕获型 recorder 替身
（非 mock 框架）驱动真实 run_conversation / run_agent_turn 代码路径。
"""

import pytest

from app.llm.core.base import BaseLLMClient, StreamEvent
from app.llm.core.types import ChatResponse, Message, Role, StopReason, Usage
from app.llm.runner import run_conversation
from app.engine.orchestrator.invoker import run_agent_turn


class ScriptedClient(BaseLLMClient):
    """单轮即结束的协议客户端替身：返回固定 usage（含缓存字段）"""

    protocol = "openai"

    def __init__(self, model="test-model"):
        self.model = model

    async def chat(self, messages, *, system=None, tools=None, max_tokens=4096,
                   temperature=None, **kwargs):
        return ChatResponse(
            message=Message(role=Role.ASSISTANT, content="ok"),
            stop_reason=StopReason.END_TURN,
            usage=Usage(input_tokens=120, output_tokens=30, cache_read_input_tokens=80),
            model=self.model,
        )

    async def chat_stream(self, messages, *, system=None, tools=None, max_tokens=4096,
                          temperature=None, **kwargs):
        yield StreamEvent("text_delta", text="ok")
        yield StreamEvent("message", response=await self.chat(messages, system=system))

    async def count_tokens(self, messages):
        return 1


class CapturingRecorder:
    """捕获 record 调用的替身（真实接口签名）"""

    def __init__(self):
        self.calls = []

    def record(self, **kwargs):
        self.calls.append(kwargs)


@pytest.fixture
def capture(monkeypatch):
    cap = CapturingRecorder()
    import app.services.token_usage_recorder as mod

    monkeypatch.setattr(mod, "token_usage_recorder", cap)
    return cap


@pytest.mark.asyncio
async def test_run_conversation_records_usage(capture):
    client = ScriptedClient()
    result = await run_conversation(
        client,
        "你好",
        task_id="task_rec_1",
        agent_key="market_analyst",
        phase="analysts",
        user_id="u1",
        max_turns=2,
    )
    assert result.final_text == "ok"
    assert len(capture.calls) == 1
    call = capture.calls[0]
    assert call["provider"] == "openai"
    assert call["model_name"] == "test-model"
    assert call["task_id"] == "task_rec_1"
    assert call["agent_key"] == "market_analyst"
    assert call["phase"] == "analysts"
    assert call["user_id"] == "u1"
    assert call["usage"].input_tokens == 120
    assert call["usage"].cache_read_input_tokens == 80


@pytest.mark.asyncio
async def test_run_agent_turn_records_usage(capture):
    client = ScriptedClient()
    text = await run_agent_turn(
        client,
        [Message(role=Role.USER, content="背景报告")],
        "你好",
        system="s",
        task_id="task_rec_2",
        agent_key="trader",
        phase="trader",
        user_id="u2",
    )
    assert text == "ok"
    assert len(capture.calls) == 1
    call = capture.calls[0]
    assert call["model_name"] == "test-model"
    assert call["agent_key"] == "trader"
    assert call["task_id"] == "task_rec_2"
    assert call["user_id"] == "u2"


@pytest.mark.asyncio
async def test_run_conversation_without_context_still_records(capture):
    """无 task/agent 上下文（脚本调用）也记录（归属字段为空串）"""
    await run_conversation(ScriptedClient(), "你好", max_turns=2)
    assert len(capture.calls) == 1
    assert capture.calls[0]["task_id"] == ""
    assert capture.calls[0]["user_id"] == ""
