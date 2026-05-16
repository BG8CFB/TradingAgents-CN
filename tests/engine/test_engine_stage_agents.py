"""
测试 Stage 2/3/4 代理的状态转换逻辑

业务逻辑测试：使用 RecordingLLM 测试 prompt 构造和状态转换
LLM 集成测试：标记 @pytest.mark.ai，使用真实 API
"""

import copy
import json
import os
import tempfile
import pytest
from langchain_core.messages import AIMessage

from app.engine.agents.stage_2.bull_researcher import create_bull_researcher
from app.engine.agents.stage_2.bear_researcher import create_bear_researcher
from app.engine.agents.stage_3.aggresive_debator import create_risky_debator
from app.engine.agents.stage_3.conservative_debator import create_safe_debator
from app.engine.agents.stage_3.neutral_debator import create_neutral_debator
from app.engine.agents.stage_3.risk_manager import create_risk_manager
from app.engine.agents.stage_4.summary_agent import create_summary_agent


class RecordingLLM:
    """记录调用的 LLM（真实类，非 MagicMock）"""

    def __init__(self, response_text="分析报告内容"):
        self.calls = []
        self.response_text = response_text

    def invoke(self, messages):
        self.calls.append(messages)
        return AIMessage(content=self.response_text)


class RecordingMemory:
    """记录调用的内存对象"""

    def __init__(self):
        self.situations = []

    def add_situations(self, situations):
        self.situations.extend(situations)


def _base_state():
    return {
        "messages": [],
        "company_of_interest": "000001",
        "trade_date": "2024-12-31",
        "task_id": "test-task-001",
        "investment_debate_state": {
            "history": "",
            "current_response": "",
            "count": 0,
            "current_round_index": 0,
            "max_rounds": 2,
            "rounds": [],
            "bull_report_content": "",
            "bear_report_content": "",
            "bull_history": "",
            "bear_history": "",
            "judge_decision": "",
        },
        "risk_debate_state": {
            "history": "",
            "current_risky_response": "",
            "current_safe_response": "",
            "current_neutral_response": "",
            "count": 0,
            "latest_speaker": "",
            "risky_history": "",
            "safe_history": "",
            "neutral_history": "",
            "judge_decision": "",
            "rounds": [],
            "current_round_index": 0,
            "max_rounds": 3,
            "risky_report_content": "",
            "safe_report_content": "",
            "neutral_report_content": "",
        },
        "reports": {
            "market_report": "市场技术指标显示上升趋势",
            "fundamentals_report": "基本面稳健",
        },
        "market_report": "市场技术指标显示上升趋势",
        "fundamentals_report": "基本面稳健",
        "trader_investment_plan": "建议买入100股",
    }


# ===== Stage 4: Summary Agent =====

class TestSummaryAgentBehavior:
    def test_collects_all_report_fields(self):
        llm = RecordingLLM(json.dumps({
            "key_indicators": {"entry_price": "12.5", "target_price": "15", "stop_loss": "11"},
            "model_confidence": 75,
            "risk_assessment": {"level": "Medium", "score": 5.0, "description": "中等风险"},
            "analysis_summary": "综合分析",
            "investment_recommendation": "建议买入",
            "analysis_reference": [],
            "final_signal": "Buy",
        }))
        node = create_summary_agent(llm)
        state = {
            "company_of_interest": "000001",
            "market_report": "市场报告",
            "news_report": "新闻报告",
            "fundamentals_report": "基本面报告",
            "trader_investment_plan": "买入计划",
            "risk_debate_state": {"history": "辩论历史"},
            "reports": {},
        }
        result = node(state)
        assert "structured_summary" in result
        assert result["structured_summary"]["model_confidence"] == 75
        assert result["structured_summary"]["final_signal"] == "Buy"

    def test_handles_json_decode_error(self):
        llm = RecordingLLM("not valid json")
        node = create_summary_agent(llm)
        state = {"company_of_interest": "000001", "risk_debate_state": {}}
        result = node(state)
        assert "structured_summary" in result
        assert result["structured_summary"]["model_confidence"] == 50
        assert result["structured_summary"]["final_signal"] == "Hold"

    def test_handles_llm_exception(self):
        class FailingLLM:
            def invoke(self, messages):
                raise RuntimeError("LLM 服务不可用")

        node = create_summary_agent(FailingLLM())
        state = {"company_of_interest": "000001", "risk_debate_state": {}}
        result = node(state)
        assert "structured_summary" in result
        assert result["structured_summary"]["model_confidence"] == 0

    def test_cleans_markdown_json(self):
        llm = RecordingLLM('```json\n{"key_indicators": {}, "model_confidence": 80, "risk_assessment": {"level": "Low", "score": 3.0, "description": "低风险"}, "analysis_summary": "测试", "investment_recommendation": "持有", "analysis_reference": [], "final_signal": "Hold"}\n```')
        node = create_summary_agent(llm)
        state = {"company_of_interest": "000001", "risk_debate_state": {}}
        result = node(state)
        assert result["structured_summary"]["model_confidence"] == 80

    def test_empty_state_defaults(self):
        llm = RecordingLLM(json.dumps({
            "key_indicators": {"entry_price": "N/A", "target_price": "N/A", "stop_loss": "N/A"},
            "model_confidence": 0,
            "risk_assessment": {"level": "Low", "score": 0.0, "description": "无数据"},
            "analysis_summary": "数据获取失败",
            "investment_recommendation": "无建议",
            "analysis_reference": [],
            "final_signal": "Hold",
        }))
        node = create_summary_agent(llm)
        state = {"company_of_interest": "Unknown", "risk_debate_state": {}}
        result = node(state)
        assert result["structured_summary"]["model_confidence"] == 0

    def test_llm_receives_all_reports(self):
        llm = RecordingLLM(json.dumps({
            "key_indicators": {}, "model_confidence": 60,
            "risk_assessment": {"level": "Medium", "score": 5.0, "description": "test"},
            "analysis_summary": "test", "investment_recommendation": "test",
            "analysis_reference": [], "final_signal": "Hold",
        }))
        node = create_summary_agent(llm)
        state = {
            "company_of_interest": "000001",
            "market_report": "市场分析详情",
            "news_report": "新闻摘要",
            "trader_investment_plan": "交易计划",
            "final_trade_decision": "最终决策",
            "risk_debate_state": {"history": "辩论记录"},
            "sentiment_report": "情绪报告",
            "custom_report": "自定义报告内容",
        }
        result = node(state)

        assert len(llm.calls) == 1
        messages = llm.calls[0]
        system_content = messages[0].content
        assert "市场分析详情" in system_content
        assert "交易计划" in system_content
        assert "最终决策" in system_content
        assert "自定义报告内容" in system_content


class TestStageAgentsWithRealLLM:
    """使用真实 LLM API 的 Stage Agent 测试"""

    @pytest.mark.ai
    def test_summary_with_real_llm(self):
        from app.engine.llm_adapters.factory import create_llm
        import os

        api_key = os.environ.get("DEEPSEEK_API_KEY")
        if not api_key:
            pytest.skip("需要 DEEPSEEK_API_KEY 环境变量")

        llm = create_llm(provider="deepseek", model="deepseek-chat", api_key=api_key)
        node = create_summary_agent(llm)
        state = {
            "company_of_interest": "000001",
            "market_report": "市场技术指标显示上升趋势",
            "fundamentals_report": "基本面稳健",
            "trader_investment_plan": "建议买入",
            "risk_debate_state": {"history": "辩论已完成"},
        }
        result = node(state)
        assert "structured_summary" in result
        assert "final_signal" in result["structured_summary"]
        assert result["structured_summary"]["model_confidence"] >= 0
