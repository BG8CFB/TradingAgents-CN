"""旧 state 外部契约冻结测试。

内部 state 已 TypedDict/canonical 化（rounds 单一数据源），对外暴露的
final_state（export_legacy_state 出口）键形状不得变化：
- analysis_service 的结果提取、前端报告渲染、_log_state 都依赖这些键。
- 本文件是重构防护网：任何键增删都应在此显式更新契约。
"""

import pytest

from app.engine.orchestrator.state import (
    append_round,
    create_initial_state,
    export_legacy_state,
)

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


class TestCanonicalInitialState:
    """canonical 内部形状：debate 子状态只有单一数据源字段"""

    def test_canonical_investment_keys(self, state):
        assert set(state["investment_debate_state"].keys()) <= {
            "rounds", "count", "max_rounds", "judge_decision",
        }
        assert state["investment_debate_state"]["count"] == 0
        assert state["investment_debate_state"]["rounds"] == []

    def test_canonical_risk_keys(self, state):
        assert set(state["risk_debate_state"].keys()) <= {
            "rounds", "count", "max_rounds", "latest_speaker", "judge_decision",
        }

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


class TestExportedLegacyContract:
    """出口契约：export_legacy_state 重建的旧键形状与旧版完全一致"""

    def test_top_level_keys(self, state):
        exported = export_legacy_state(state)
        assert TOP_LEVEL_KEYS <= set(exported.keys())

    def test_investment_debate_keys(self, state):
        exported = export_legacy_state(state)
        assert set(exported["investment_debate_state"].keys()) == INVESTMENT_DEBATE_KEYS

    def test_risk_debate_keys(self, state):
        exported = export_legacy_state(state)
        assert set(exported["risk_debate_state"].keys()) == RISK_DEBATE_KEYS

    def test_initial_values(self, state):
        exported = export_legacy_state(state)
        ids = exported["investment_debate_state"]
        rds = exported["risk_debate_state"]
        assert ids["count"] == 0 and ids["max_rounds"] == 2
        assert rds["count"] == 0 and rds["max_rounds"] == 3
        assert ids["history"] == "" and rds["history"] == ""
        assert exported["reports"] == {}
        assert exported["final_trade_decision"] == ""


class TestDerivedViews:
    """rounds 单一数据源 → 派生视图语义（与旧累积语义一致）"""

    def test_investment_views_after_two_rounds(self, state):
        ids = state["investment_debate_state"]
        append_round(ids, "bull", "bull r0", 2)
        append_round(ids, "bear", "bear r0", 2)
        append_round(ids, "bull", "bull r1", 2)
        append_round(ids, "bear", "bear r1", 2)

        exported = export_legacy_state(state)["investment_debate_state"]
        assert ids["count"] == 4
        assert exported["current_round_index"] == 2
        # history：bull 全部观点在前、bear 在后，argument 前缀带轮次
        assert "bull r0" in exported["history"] and "bear r1" in exported["history"]
        assert "# 【多头分析师 - 初始报告】\nbull r0" in exported["history"]
        assert "# 【空头分析师 - 第 1 轮辩论】\nbear r1" in exported["history"]
        # side_history 只含己方
        assert "bear" not in exported["bull_history"]
        assert "bull" not in exported["bear_history"]
        # report_content 分节
        assert "## 初始报告：核心投资论点" in exported["bull_report_content"]
        assert "## 第 1 轮辩论报告：针对空方观点的反驳与辩护" in exported["bull_report_content"]
        # current_response = 最近一次发言（bear r1）
        assert exported["current_response"].endswith("bear r1")

    def test_risk_views_after_one_round(self, state):
        rds = state["risk_debate_state"]
        append_round(rds, "risky", "risky r0", 3)
        append_round(rds, "safe", "safe r0", 3)

        exported = export_legacy_state(state)["risk_debate_state"]
        assert rds["count"] == 2
        assert exported["current_round_index"] == 0  # 2//3
        assert "risky r0" in exported["history"] and "safe r0" in exported["history"]
        assert exported["current_risky_response"] == "risky r0"
        assert exported["current_safe_response"] == "safe r0"
        assert exported["current_neutral_response"] == ""
        assert "## 初始观点：激进策略" in exported["risky_report_content"]

    def test_export_does_not_mutate_input(self, state):
        ids = state["investment_debate_state"]
        append_round(ids, "bull", "x", 2)
        before_keys = set(ids.keys())
        export_legacy_state(state)
        assert set(ids.keys()) == before_keys  # 不写回 legacy 键

    def test_legacy_shaped_input_passthrough(self):
        """旧形状 debate state（历史数据/测试构造）可安全导出"""
        legacy = {
            "history": "旧历史",
            "bull_history": "旧多头",
            "current_response": "旧响应",
            "count": 2,
            "current_round_index": 1,
            "max_rounds": 2,
            "rounds": [],
            "bull_report_content": "旧报告",
            "bear_report_content": "",
            "bear_history": "",
            "judge_decision": "",
        }
        state = {"investment_debate_state": legacy}
        exported = export_legacy_state(state)["investment_debate_state"]
        assert exported["history"] == "旧历史"
        assert exported["bull_report_content"] == "旧报告"
        assert exported["current_response"] == "旧响应"
