"""
测试 Stage 4 总结智能体

业务逻辑测试：create_summary_agent 工厂函数
LLM 集成测试：标记 @pytest.mark.ai，使用真实 API
"""

import json
import pytest
from langchain_core.messages import AIMessage

from app.engine.agents.stage_4.summary_agent import create_summary_agent


class TestCreateSummaryAgent:
    def test_returns_callable(self):
        node = create_summary_agent(llm=None)
        assert callable(node)


class RecordingLLM:
    """记录调用的 LLM（真实类）"""

    def __init__(self, response_content):
        self.calls = []
        self.response_content = response_content

    def invoke(self, messages):
        self.calls.append(messages)
        return AIMessage(content=self.response_content)


class TestSummaryNodePromptConstruction:
    """测试 summary_agent 的 prompt 构造逻辑"""

    def test_llm_receives_all_report_fields(self):
        """验证 LLM 收到的 prompt 包含各报告字段"""
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

        # 验证 LLM 被调用且 prompt 包含报告内容
        assert len(llm.calls) == 1
        messages = llm.calls[0]
        system_content = messages[0].content
        assert "市场分析详情" in system_content
        assert "交易计划" in system_content
        assert "最终决策" in system_content
        assert "自定义报告内容" in system_content

        # 验证返回结构
        assert "structured_summary" in result
        assert result["structured_summary"]["model_confidence"] == 60


class TestSummaryWithRealLLM:
    """使用真实 LLM 的 summary 测试"""

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
            "final_trade_decision": "建议持有",
            "risk_debate_state": {"history": "辩论已完成"},
        }
        result = node(state)
        assert "structured_summary" in result
        assert "final_signal" in result["structured_summary"]
