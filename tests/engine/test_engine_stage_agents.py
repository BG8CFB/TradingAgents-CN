"""
测试 Stage 2/3/4 代理的状态转换逻辑

业务逻辑测试：使用 RecordingLLM 测试 prompt 构造和状态转换
LLM 集成测试：标记 @pytest.mark.ai，使用真实 API
"""

import json
import pytest

from app.engine.agents.stage_4.summary_agent import create_summary_agent
from app.llm.core.types import ChatResponse, Message, Role, StopReason


def _chat_response(text: str) -> ChatResponse:
    return ChatResponse(
        message=Message(role=Role.ASSISTANT, content=text),
        stop_reason=StopReason.END_TURN,
    )


class RecordingLLM:
    """记录调用的 LLM（真实类，非 MagicMock）。

    实现新层 BaseLLMClient 的 chat 协议（async chat -> ChatResponse），
    生产代码经 orchestrator/llm_bridge.llm_chat 调用本类。
    """

    def __init__(self, response_text="分析报告内容"):
        self.calls = []
        self.response_text = response_text

    async def chat(self, messages, *, system=None, **kwargs):
        self.calls.append({"messages": list(messages), "system": system})
        return _chat_response(self.response_text)


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
    @pytest.mark.asyncio
    async def test_collects_all_report_fields(self):
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
        result = await node(state)
        assert "structured_summary" in result
        assert result["structured_summary"]["model_confidence"] == 75
        assert result["structured_summary"]["final_signal"] == "Buy"

    @pytest.mark.asyncio
    async def test_handles_json_decode_error(self):
        llm = RecordingLLM("not valid json")
        node = create_summary_agent(llm)
        state = {"company_of_interest": "000001", "risk_debate_state": {}}
        result = await node(state)
        assert "structured_summary" in result
        assert result["structured_summary"]["model_confidence"] == 50
        assert result["structured_summary"]["final_signal"] == "Hold"

    @pytest.mark.asyncio
    async def test_handles_llm_exception(self):
        class FailingLLM:
            async def chat(self, messages, *, system=None, **kwargs):
                raise RuntimeError("LLM 服务不可用")

        node = create_summary_agent(FailingLLM())
        state = {"company_of_interest": "000001", "risk_debate_state": {}}
        result = await node(state)
        assert "structured_summary" in result
        assert result["structured_summary"]["model_confidence"] == 0

    @pytest.mark.asyncio
    async def test_cleans_markdown_json(self):
        llm = RecordingLLM('```json\n{"key_indicators": {}, "model_confidence": 80, "risk_assessment": {"level": "Low", "score": 3.0, "description": "低风险"}, "analysis_summary": "测试", "investment_recommendation": "持有", "analysis_reference": [], "final_signal": "Hold"}\n```')
        node = create_summary_agent(llm)
        state = {"company_of_interest": "000001", "risk_debate_state": {}}
        result = await node(state)
        assert result["structured_summary"]["model_confidence"] == 80

    @pytest.mark.asyncio
    async def test_empty_state_defaults(self):
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
        result = await node(state)
        assert result["structured_summary"]["model_confidence"] == 0

    @pytest.mark.asyncio
    async def test_llm_receives_all_reports(self):
        """H4 后契约：动态内容在 USER 消息而非 system 参数。

        用独特标记词避免与 SYSTEM_PROMPT 静态字段描述词冲突。
        """
        llm = RecordingLLM(json.dumps({
            "key_indicators": {}, "model_confidence": 60,
            "risk_assessment": {"level": "Medium", "score": 5.0, "description": "test"},
            "analysis_summary": "test", "investment_recommendation": "test",
            "analysis_reference": [], "final_signal": "Hold",
        }))
        node = create_summary_agent(llm)
        state = {
            "company_of_interest": "000001",
            "market_report": "MARKET_DETAIL_MARKER",
            "news_report": "NEWS_MARKER",
            "trader_investment_plan": "TRADER_PLAN_MARKER",
            "final_trade_decision": "FINAL_DECISION_MARKER",
            "risk_debate_state": {"history": "DEBATE_MARKER"},
            "sentiment_report": "SENTIMENT_MARKER",
            "custom_report": "CUSTOM_MARKER",
        }
        # 不接受 result：仅用 llm.calls 验证 prompt 构造
        await node(state)

        assert len(llm.calls) == 1
        call = llm.calls[0]
        assert len(call["messages"]) == 1  # 单条 USER 消息（system 走独立参数）

        system_content = call["system"]
        human_content = call["messages"][0].content

        # 反向断言：独特标记词绝不能出现在静态 SYSTEM_PROMPT 中
        assert "MARKET_DETAIL_MARKER" not in system_content
        assert "TRADER_PLAN_MARKER" not in system_content
        assert "FINAL_DECISION_MARKER" not in system_content

        # 正向断言：动态内容在 USER 消息的 XML 边界符内
        assert "MARKET_DETAIL_MARKER" in human_content
        assert "TRADER_PLAN_MARKER" in human_content
        assert "FINAL_DECISION_MARKER" in human_content
        assert "CUSTOM_MARKER" in human_content


class TestStageAgentsWithRealLLM:
    """使用真实 LLM API 的 Stage Agent 测试（app/llm 新层客户端）"""

    @pytest.mark.ai
    @pytest.mark.asyncio
    async def test_summary_with_real_llm(self):
        from tests.engine.test_engine_reflection import _build_real_llm_client

        llm = _build_real_llm_client()
        if llm is None:
            pytest.skip("无可用 LLM 凭据（DEEPSEEK_API_KEY 或 ARK_API_KEY）")

        node = create_summary_agent(llm)
        state = {
            "company_of_interest": "000001",
            "market_report": "市场技术指标显示上升趋势",
            "fundamentals_report": "基本面稳健",
            "trader_investment_plan": "建议买入",
            "risk_debate_state": {"history": "辩论已完成"},
        }
        result = await node(state)
        assert "structured_summary" in result
        assert "final_signal" in result["structured_summary"]
        assert result["structured_summary"]["model_confidence"] >= 0
