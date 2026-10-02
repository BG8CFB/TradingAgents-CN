"""
测试 Reflector 反思模块（agents/postprocess/reflector.py，async 统一调用路径）

P4-b 起反思为声明驱动单入口 reflect_component（旧 5 个按内置槽读死键的专用
方法已删除；各槽位输入派生的等价测试见 tests/engine/workflow/
test_p4b_terminal_contract.py 的 TestReflectionInput / TestReflectAndRemember）。

业务逻辑测试：prompt 构造、situation 注入、空输入/失败降级（记录型
BaseLLMClient 替身驱动真实 run_agent_turn → run_conversation 代码路径）
LLM 集成测试：标记 @pytest.mark.ai，使用真实 API
"""

import pytest

from app.engine.agents.postprocess.reflector import Reflector
from app.llm.core.base import BaseLLMClient, StreamEvent
from app.llm.core.types import ChatResponse, Message, Role, StopReason


def _chat_response(text: str) -> ChatResponse:
    return ChatResponse(
        message=Message(role=Role.ASSISTANT, content=text),
        stop_reason=StopReason.END_TURN,
    )


def _build_real_llm_client():
    """基于 app/llm 新层构建真实客户端（DEEPSEEK_API_KEY 优先，ARK 回退）。

    无可用凭据时返回 None，由调用方 skip。
    """
    import os
    from pathlib import Path

    try:
        from dotenv import load_dotenv

        load_dotenv(Path(__file__).resolve().parents[2] / ".env", override=False)
    except ImportError:
        pass

    from app.llm.config import load_config
    from app.llm.providers import ResolvedProvider, build_client

    deepseek_key = os.environ.get("DEEPSEEK_API_KEY")
    if deepseek_key:
        rp = ResolvedProvider(
            protocol="openai",
            model="deepseek-chat",
            api_key=deepseek_key,
            base_url="https://api.deepseek.com",
            source="env",
        )
        return build_client(rp)

    cfg = load_config()
    if cfg.api_key:
        rp = ResolvedProvider(
            protocol="anthropic",
            model=cfg.default_model,
            api_key=cfg.api_key,
            base_url=cfg.anthropic_base_url,
            source="env",
        )
        return build_client(rp)
    return None


class RecordingMemory:
    """记录调用情况的内存对象（真实类，非 MagicMock）"""

    def __init__(self):
        self.situations = []

    def add_situations(self, situations):
        self.situations.extend(situations)


class RecordingLLM(BaseLLMClient):
    """记录调用情况的 LLM 对象（真实类，非 MagicMock）。

    实现新层 BaseLLMClient 协议（chat / chat_stream / count_tokens），
    Reflector 经 invoker.run_agent_turn → run_conversation 调用本类。
    """

    protocol = "openai"

    def __init__(self, response_content="反思结果：需要改进风险控制"):
        self.model = "recording-model"
        self.calls = []
        self.response_content = response_content

    async def chat(self, messages, *, system=None, tools=None, max_tokens=4096, temperature=None, **kwargs):
        self.calls.append({"messages": list(messages), "system": system})
        return _chat_response(self.response_content)

    async def chat_stream(self, messages, *, system=None, tools=None, max_tokens=4096, temperature=None, **kwargs):
        resp = await self.chat(messages, system=system)
        yield StreamEvent("message", response=resp)

    async def count_tokens(self, messages):
        return 1


class TestReflectorInit:
    def test_init_stores_llm(self):
        llm = RecordingLLM()
        r = Reflector(llm)
        assert r.llm is llm

    def test_init_generates_reflection_prompt(self):
        r = Reflector(RecordingLLM())
        assert r.reflection_system_prompt is not None
        assert len(r.reflection_system_prompt) > 0
        assert "推理" in r.reflection_system_prompt
        assert "改进" in r.reflection_system_prompt


class TestExtractCurrentSituation:
    """测试状态信息提取（纯逻辑，不调用 LLM）"""

    def test_collects_all_report_fields(self):
        r = Reflector(RecordingLLM())
        state = {
            "market_report": "市场报告内容",
            "fundamentals_report": "基本面报告内容",
            "news_report": "新闻报告内容",
            "messages": [],
            "company_of_interest": "000001",
        }
        result = r._extract_current_situation(state)
        assert "市场报告内容" in result
        assert "基本面报告内容" in result
        assert "新闻报告内容" in result

    def test_ignores_empty_report_values(self):
        r = Reflector(RecordingLLM())
        state = {
            "market_report": "市场报告",
            "fundamentals_report": "",
            "news_report": None,
            "messages": [],
        }
        result = r._extract_current_situation(state)
        assert "市场报告" in result
        assert "基本面报告" not in result

    def test_no_reports_returns_empty(self):
        r = Reflector(RecordingLLM())
        state = {"messages": [], "company_of_interest": "000001"}
        result = r._extract_current_situation(state)
        assert result == ""


class TestReflectComponent:
    """声明驱动单入口（P4-b）：prompt 构造 / situation 注入 / 降级语义"""

    async def test_calls_llm_with_correct_structure(self):
        llm = RecordingLLM()
        memory = RecordingMemory()
        r = Reflector(llm)
        state = {"market_report": "市场情况"}
        wrote = await r.reflect_component("BULL", "看涨报告", state, "盈利5%", memory)

        assert wrote is True
        assert len(llm.calls) == 1
        call = llm.calls[0]
        # system 走独立参数（新层契约），包含静态反思 prompt
        assert "推理" in call["system"]
        assert "改进" in call["system"]
        # 消息列表仅含一条 USER 消息
        assert len(call["messages"]) == 1
        msg = call["messages"][0]
        assert msg.role == Role.USER
        assert "盈利5%" in msg.content
        assert "看涨报告" in msg.content
        assert "市场情况" in msg.content  # situation（*_report 顶层键）注入同一 prompt
        # 反思结论写入记忆库（situation, lesson) 二元组
        assert len(memory.situations) == 1
        assert isinstance(memory.situations[0], tuple)
        assert memory.situations[0][1] == "反思结果：需要改进风险控制"

    async def test_component_key_used_for_token_attribution(self):
        """component_key 进入 agent_key（自定义节点 = slug，token 用量归属可区分）"""
        llm = RecordingLLM()
        r = Reflector(llm)
        await r.reflect_component("macro-debater", "宏观发言史", {}, "盈利5%", RecordingMemory())
        assert len(llm.calls) == 1

    async def test_empty_report_skips(self):
        """空输入跳过（P4-b 行为变更：不再对空历史发起无意义反思调用）"""
        llm = RecordingLLM()
        r = Reflector(llm)
        wrote = await r.reflect_component("BULL", "", {}, "盈利5%", RecordingMemory())
        assert wrote is False
        assert llm.calls == []

    async def test_none_memory_skips(self):
        llm = RecordingLLM()
        r = Reflector(llm)
        wrote = await r.reflect_component("BULL", "看涨报告", {}, "盈利5%", None)
        assert wrote is False
        assert llm.calls == []

    async def test_llm_failure_returns_false_without_write(self):
        """反思 LLM 调用失败：返回 False、不写记忆（异常不外抛）"""

        class FailingLLM(RecordingLLM):
            async def chat(self, messages, **kwargs):
                raise RuntimeError("provider down")

        llm = FailingLLM()
        memory = RecordingMemory()
        r = Reflector(llm)
        wrote = await r.reflect_component("BULL", "看涨报告", {}, "盈利5%", memory)
        assert wrote is False
        assert memory.situations == []


class TestReflectorWithRealLLM:
    """使用真实 LLM API 的反思测试（app/llm 新层客户端）"""

    @pytest.mark.ai
    async def test_reflect_component_with_real_llm(self, sample_agent_state):
        llm = _build_real_llm_client()
        if llm is None:
            pytest.skip("无可用 LLM 凭据（DEEPSEEK_API_KEY 或 ARK_API_KEY）")

        r = Reflector(llm)
        memory = RecordingMemory()
        wrote = await r.reflect_component("BULL", "看涨发言史：看好市场", sample_agent_state, "盈利5%", memory)

        assert wrote is True
        assert len(memory.situations) == 1
        assert len(memory.situations[0]) == 2
