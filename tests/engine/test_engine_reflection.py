"""
测试 Reflector 反思模块

业务逻辑测试：测试 prompt 构造和状态提取逻辑
LLM 集成测试：标记 @pytest.mark.ai，使用真实 API
"""

import pytest
from langchain_core.messages import AIMessage

from app.engine.graph.reflection import Reflector


class RecordingMemory:
    """记录调用情况的内存对象（真实类，非 MagicMock）"""

    def __init__(self):
        self.situations = []

    def add_situations(self, situations):
        self.situations.extend(situations)


class RecordingLLM:
    """记录调用情况的 LLM 对象（真实类，非 MagicMock）"""

    def __init__(self, response_content="反思结果：需要改进风险控制"):
        self.calls = []
        self.response_content = response_content

    def invoke(self, messages):
        self.calls.append(messages)
        return AIMessage(content=self.response_content)


class TestReflectorInit:
    def test_init_stores_llm(self):
        llm = RecordingLLM()
        r = Reflector(llm)
        assert r.quick_thinking_llm is llm

    def test_init_generates_reflection_prompt(self):
        r = Reflector(RecordingLLM())
        assert r.reflection_system_prompt is not None
        assert len(r.reflection_system_prompt) > 0
        assert "Reasoning" in r.reflection_system_prompt
        assert "Improvement" in r.reflection_system_prompt


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


class TestReflectOnComponent:
    """测试组件反思（使用 RecordingLLM 验证 prompt 构造）"""

    def test_calls_llm_with_correct_structure(self):
        llm = RecordingLLM()
        r = Reflector(llm)
        r._reflect_on_component("BULL", "看涨报告", "市场情况", "盈利5%")

        assert len(llm.calls) == 1
        messages = llm.calls[0]
        assert len(messages) == 2
        assert messages[0][0] == "system"
        assert messages[1][0] == "human"
        assert "盈利5%" in messages[1][1]
        assert "看涨报告" in messages[1][1]


class TestReflectBullResearcher:
    def test_extracts_bull_history_and_updates_memory(self, sample_agent_state):
        llm = RecordingLLM()
        memory = RecordingMemory()
        r = Reflector(llm)
        r.reflect_bull_researcher(sample_agent_state, "盈利5%", memory)

        assert len(llm.calls) == 1
        assert len(memory.situations) == 1
        assert isinstance(memory.situations[0], tuple)

    def test_uses_investment_debate_state(self, sample_agent_state):
        llm = RecordingLLM()
        r = Reflector(llm)
        r.reflect_bull_researcher(sample_agent_state, "盈利5%", RecordingMemory())

        messages = llm.calls[0]
        human_msg = messages[1][1]
        assert "看好市场" in human_msg


class TestReflectBearResearcher:
    def test_extracts_bear_history(self, sample_agent_state):
        llm = RecordingLLM()
        r = Reflector(llm)
        r.reflect_bear_researcher(sample_agent_state, "亏损3%", RecordingMemory())

        messages = llm.calls[0]
        human_msg = messages[1][1]
        assert "看空市场" in human_msg


class TestReflectTrader:
    def test_extracts_trader_investment_plan(self, sample_agent_state):
        sample_agent_state["trader_investment_plan"] = "建议买入100股"
        llm = RecordingLLM()
        r = Reflector(llm)
        r.reflect_trader(sample_agent_state, "盈利5%", RecordingMemory())

        messages = llm.calls[0]
        human_msg = messages[1][1]
        assert "建议买入100股" in human_msg


class TestReflectInvestJudge:
    def test_extracts_judge_decision_from_investment(self, sample_agent_state):
        llm = RecordingLLM()
        r = Reflector(llm)
        r.reflect_invest_judge(sample_agent_state, "盈利5%", RecordingMemory())

        messages = llm.calls[0]
        human_msg = messages[1][1]
        assert "裁决结果" in human_msg


class TestReflectRiskManager:
    def test_extracts_judge_decision_from_risk(self, sample_agent_state):
        llm = RecordingLLM()
        r = Reflector(llm)
        r.reflect_risk_manager(sample_agent_state, "亏损3%", RecordingMemory())

        messages = llm.calls[0]
        human_msg = messages[1][1]
        assert "风控裁决" in human_msg


class TestReflectorWithRealLLM:
    """使用真实 LLM API 的反思测试"""

    @pytest.mark.ai
    def test_reflect_bull_with_real_llm(self, sample_agent_state):
        from app.engine.llm_adapters.factory import create_llm
        import os

        api_key = os.environ.get("DEEPSEEK_API_KEY")
        if not api_key:
            pytest.skip("需要 DEEPSEEK_API_KEY 环境变量")

        llm = create_llm(provider="deepseek", model="deepseek-chat", api_key=api_key)
        r = Reflector(llm)
        memory = RecordingMemory()
        r.reflect_bull_researcher(sample_agent_state, "盈利5%", memory)

        assert len(memory.situations) == 1
        assert len(memory.situations[0]) == 2
