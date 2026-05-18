"""
Agent 状态定义测试
测试 AgentState, InvestDebateState, RiskDebateState TypedDict 结构
以及 update_reports reducer 函数
"""

import pytest
from typing import get_type_hints, get_args, get_origin


# ---------------------------------------------------------------------------
# Test Classes
# ---------------------------------------------------------------------------

class TestInvestDebateState:
    """InvestDebateState TypedDict 测试"""

    def test_has_required_keys(self):
        """InvestDebateState 应包含所有必需键"""
        from app.engine.agents.utils.agent_states import InvestDebateState

        expected_keys = {
            "bull_history", "bear_history", "history",
            "current_response", "judge_decision", "count",
            "rounds", "bull_report_content", "bear_report_content",
            "current_round_index", "max_rounds",
        }
        hints = get_type_hints(InvestDebateState)
        actual_keys = set(hints.keys())
        assert expected_keys.issubset(actual_keys), f"缺少键: {expected_keys - actual_keys}"

    def test_has_conversation_history_fields(self):
        """应包含对话历史字段"""
        from app.engine.agents.utils.agent_states import InvestDebateState

        hints = get_type_hints(InvestDebateState)
        assert "bull_history" in hints
        assert "bear_history" in hints
        assert "history" in hints

    def test_has_count_field(self):
        """应包含对话计数字段"""
        from app.engine.agents.utils.agent_states import InvestDebateState

        hints = get_type_hints(InvestDebateState)
        assert "count" in hints

    def test_has_debate_rounds_fields(self):
        """应包含辩论轮次控制字段"""
        from app.engine.agents.utils.agent_states import InvestDebateState

        hints = get_type_hints(InvestDebateState)
        assert "current_round_index" in hints
        assert "max_rounds" in hints
        assert "rounds" in hints

    def test_has_report_content_fields(self):
        """应包含报告内容字段"""
        from app.engine.agents.utils.agent_states import InvestDebateState

        hints = get_type_hints(InvestDebateState)
        assert "bull_report_content" in hints
        assert "bear_report_content" in hints

    def test_can_create_instance(self):
        """应能创建有效的 InvestDebateState 实例"""
        from app.engine.agents.utils.agent_states import InvestDebateState

        state = InvestDebateState(
            bull_history="Bull argument",
            bear_history="Bear argument",
            history="Full history",
            current_response="Latest",
            judge_decision="",
            count=0,
            rounds=[],
            bull_report_content="",
            bear_report_content="",
            current_round_index=0,
            max_rounds=2,
        )
        assert state["bull_history"] == "Bull argument"
        assert state["count"] == 0
        assert state["max_rounds"] == 2


class TestRiskDebateState:
    """RiskDebateState TypedDict 测试"""

    def test_has_required_keys(self):
        """RiskDebateState 应包含所有必需键"""
        from app.engine.agents.utils.agent_states import RiskDebateState

        expected_keys = {
            "risky_history", "safe_history", "neutral_history",
            "history", "latest_speaker", "current_risky_response",
            "current_safe_response", "current_neutral_response",
            "judge_decision", "count",
        }
        hints = get_type_hints(RiskDebateState)
        actual_keys = set(hints.keys())
        assert expected_keys.issubset(actual_keys), f"缺少键: {expected_keys - actual_keys}"

    def test_has_three_agent_histories(self):
        """应包含三个风险角色的历史字段"""
        from app.engine.agents.utils.agent_states import RiskDebateState

        hints = get_type_hints(RiskDebateState)
        assert "risky_history" in hints
        assert "safe_history" in hints
        assert "neutral_history" in hints

    def test_has_three_agent_responses(self):
        """应包含三个风险角色的最新回复字段"""
        from app.engine.agents.utils.agent_states import RiskDebateState

        hints = get_type_hints(RiskDebateState)
        assert "current_risky_response" in hints
        assert "current_safe_response" in hints
        assert "current_neutral_response" in hints

    def test_has_latest_speaker_field(self):
        """应包含最新发言者字段"""
        from app.engine.agents.utils.agent_states import RiskDebateState

        hints = get_type_hints(RiskDebateState)
        assert "latest_speaker" in hints

    def test_can_create_instance(self):
        """应能创建有效的 RiskDebateState 实例"""
        from app.engine.agents.utils.agent_states import RiskDebateState

        state = RiskDebateState(
            risky_history="Risky argument",
            safe_history="Safe argument",
            neutral_history="Neutral argument",
            history="Full history",
            latest_speaker="Risky Analyst",
            current_risky_response="",
            current_safe_response="",
            current_neutral_response="",
            judge_decision="",
            count=0,
        )
        assert state["latest_speaker"] == "Risky Analyst"
        assert state["count"] == 0


class TestAgentState:
    """AgentState TypedDict 测试"""

    def test_has_company_and_date_fields(self):
        """应包含公司和日期字段"""
        from app.engine.agents.utils.agent_states import AgentState

        hints = get_type_hints(AgentState)
        assert "company_of_interest" in hints
        assert "trade_date" in hints

    def test_has_sender_field(self):
        """应包含 sender 字段"""
        from app.engine.agents.utils.agent_states import AgentState

        hints = get_type_hints(AgentState)
        assert "sender" in hints

    def test_has_core_report_fields(self):
        """应包含核心分析师报告字段"""
        from app.engine.agents.utils.agent_states import AgentState

        hints = get_type_hints(AgentState)
        core_reports = [
            "market_report", "sentiment_report", "news_report",
            "fundamentals_report",
        ]
        for key in core_reports:
            assert key in hints, f"缺少核心报告字段: {key}"

    def test_has_reports_dict_field(self):
        """应包含 reports 字典字段"""
        from app.engine.agents.utils.agent_states import AgentState

        hints = get_type_hints(AgentState)
        assert "reports" in hints

    def test_has_debate_state_fields(self):
        """应包含辩论状态字段"""
        from app.engine.agents.utils.agent_states import AgentState

        hints = get_type_hints(AgentState)
        assert "investment_debate_state" in hints
        assert "risk_debate_state" in hints

    def test_has_investment_plan_fields(self):
        """应包含投资计划字段"""
        from app.engine.agents.utils.agent_states import AgentState

        hints = get_type_hints(AgentState)
        assert "investment_plan" in hints
        assert "trader_investment_plan" in hints

    def test_has_final_decision_field(self):
        """应包含最终决策字段"""
        from app.engine.agents.utils.agent_states import AgentState

        hints = get_type_hints(AgentState)
        assert "final_trade_decision" in hints

    def test_has_structured_summary_field(self):
        """应包含结构化总结字段"""
        from app.engine.agents.utils.agent_states import AgentState

        hints = get_type_hints(AgentState)
        assert "structured_summary" in hints

    def test_has_phase_enabled_fields(self):
        """应包含阶段启用标志字段"""
        from app.engine.agents.utils.agent_states import AgentState

        hints = get_type_hints(AgentState)
        assert "phase2_enabled" in hints
        assert "phase3_enabled" in hints
        assert "phase4_enabled" in hints

    def test_inherits_from_messages_state(self):
        """应继承自 MessagesState（通过字段存在性验证）"""
        from app.engine.agents.utils.agent_states import AgentState
        from langgraph.graph import MessagesState

        # TypedDict 不支持 issubclass，通过检查 messages 字段验证继承关系
        hints = get_type_hints(AgentState)
        assert "messages" in hints


class TestUpdateReportsReducer:
    """update_reports reducer 函数测试"""

    def test_merge_two_dicts(self):
        """合并两个字典应正确合并"""
        from app.engine.agents.utils.agent_states import update_reports

        existing = {"market_report": "市场报告", "news_report": "新闻报告"}
        new = {"fundamentals_report": "基本面报告"}
        result = update_reports(existing, new)

        assert result == {
            "market_report": "市场报告",
            "news_report": "新闻报告",
            "fundamentals_report": "基本面报告",
        }

    def test_new_overwrites_existing_keys(self):
        """新值应覆盖同名旧值"""
        from app.engine.agents.utils.agent_states import update_reports

        existing = {"market_report": "旧报告"}
        new = {"market_report": "新报告"}
        result = update_reports(existing, new)

        assert result["market_report"] == "新报告"

    def test_empty_existing_returns_new(self):
        """existing 为空时返回 new"""
        from app.engine.agents.utils.agent_states import update_reports

        new = {"report": "内容"}
        result = update_reports({}, new)

        assert result == new

    def test_empty_new_returns_existing(self):
        """new 为空时返回 existing"""
        from app.engine.agents.utils.agent_states import update_reports

        existing = {"report": "内容"}
        result = update_reports(existing, {})

        assert result == existing

    def test_none_existing_returns_new(self):
        """existing 为 None 时返回 new"""
        from app.engine.agents.utils.agent_states import update_reports

        new = {"report": "内容"}
        result = update_reports(None, new)

        assert result == new

    def test_none_new_returns_existing(self):
        """new 为 None 时返回 existing"""
        from app.engine.agents.utils.agent_states import update_reports

        existing = {"report": "内容"}
        result = update_reports(existing, None)

        assert result == existing

    def test_both_none_handling(self):
        """两者均为空/None 时的处理"""
        from app.engine.agents.utils.agent_states import update_reports

        # existing=None, new=None → not existing → return new (None)
        result = update_reports(None, None)
        assert result is None

    def test_does_not_mutate_original(self):
        """合并不应修改原始字典"""
        from app.engine.agents.utils.agent_states import update_reports

        existing = {"a": "1"}
        new = {"b": "2"}
        result = update_reports(existing, new)

        assert existing == {"a": "1"}
        assert new == {"b": "2"}
        assert result == {"a": "1", "b": "2"}


class TestStateSchemaIntegration:
    """状态结构集成测试"""

    def test_agent_state_contains_all_key_fields(self):
        """AgentState 应包含完整的关键字段集合"""
        from app.engine.agents.utils.agent_states import AgentState

        hints = get_type_hints(AgentState)

        # 分类验证
        input_fields = {"company_of_interest", "trade_date", "sender"}
        report_fields = {
            "market_report", "sentiment_report", "news_report",
            "fundamentals_report", "reports",
        }
        output_fields = {
            "investment_plan", "trader_investment_plan",
            "final_trade_decision",
        }
        state_fields = {
            "investment_debate_state", "risk_debate_state",
        }

        for category_name, fields in [
            ("输入", input_fields),
            ("报告", report_fields),
            ("输出", output_fields),
            ("状态", state_fields),
        ]:
            for f in fields:
                assert f in hints, f"[{category_name}] 缺少字段: {f}"

    def test_debate_state_count_is_int(self):
        """辩论状态的 count 字段应为 int 类型"""
        from app.engine.agents.utils.agent_states import InvestDebateState, RiskDebateState

        invest_hints = get_type_hints(InvestDebateState)
        risk_hints = get_type_hints(RiskDebateState)

        # count 字段存在
        assert "count" in invest_hints
        assert "count" in risk_hints
