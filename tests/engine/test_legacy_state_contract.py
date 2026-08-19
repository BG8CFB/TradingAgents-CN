"""旧 state 外部契约冻结测试。

重构（TypedDict 化 / export_legacy_state）期间，对外暴露的 final_state 键形状不得变化：
- analysis_service 的结果提取、前端报告渲染、_log_state 都依赖这些键。
- 本文件是阶段 0 的防护网：任何键增删都应在此显式更新契约。
"""

import pytest

from app.engine.orchestrator.state import create_initial_state

INVESTMENT_DEBATE_KEYS = {
    "history",
    "current_response",
    "count",
    "current_round_index",
    "max_rounds",
    "rounds",
    "bull_report_content",
    "bear_report_content",
    "bull_history",
    "bear_history",
    "judge_decision",
}

RISK_DEBATE_KEYS = {
    "history",
    "current_risky_response",
    "current_safe_response",
    "current_neutral_response",
    "count",
    "latest_speaker",
    "risky_history",
    "safe_history",
    "neutral_history",
    "judge_decision",
    "rounds",
    "current_round_index",
    "max_rounds",
    "risky_report_content",
    "safe_report_content",
    "neutral_report_content",
}

TOP_LEVEL_KEYS = {
    "messages",
    "company_of_interest",
    "trade_date",
    "task_id",
    "user_id",
    "investment_debate_state",
    "risk_debate_state",
    "reports",
    "trader_investment_plan",
    "investment_plan",
    "final_trade_decision",
}


@pytest.fixture
def state():
    return create_initial_state("000001", "2024-12-31", task_id="t-contract", user_id="u1")


class TestInitialStateContract:
    def test_top_level_keys(self, state):
        assert TOP_LEVEL_KEYS <= set(state.keys())

    def test_investment_debate_keys(self, state):
        assert set(state["investment_debate_state"].keys()) == INVESTMENT_DEBATE_KEYS

    def test_risk_debate_keys(self, state):
        assert set(state["risk_debate_state"].keys()) == RISK_DEBATE_KEYS

    def test_initial_values(self, state):
        ids = state["investment_debate_state"]
        rds = state["risk_debate_state"]
        assert ids["count"] == 0 and ids["max_rounds"] == 2
        assert rds["count"] == 0 and rds["max_rounds"] == 3
        assert state["reports"] == {}
        assert state["final_trade_decision"] == ""

    def test_dynamic_analyst_report_fields(self, state):
        from app.engine.agents.analysts.dynamic_analyst import DynamicAnalystFactory

        for agent in DynamicAnalystFactory.get_all_agents():
            slug = agent.get("slug", "")
            if not slug:
                continue
            internal_key = slug.replace("-analyst", "").replace("-", "_")
            assert state.get(f"{internal_key}_report") == ""

    def test_first_message_is_task_description(self, state):
        first = state["messages"][0]
        assert first.role.value == "user"
        assert "000001" in first.content and "2024-12-31" in first.content
