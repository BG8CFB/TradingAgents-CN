"""输入渲染器测试（P3 §4.6）：黑板取值 / 占位符渲染 / required fail-fast。

纯函数直测 + 真实种子/registry 数据驱动 required 检查（无 mock）。
"""

import pytest

from app.engine.orchestrator.workflow import inputs as inputs_mod
from app.engine.orchestrator.workflow.compiler import compile_workflow
from app.engine.orchestrator.workflow.spec import CompileParams, InputSlot, StageOverride

pytestmark = pytest.mark.requires_db


# ---------------------------------------------------------------------------
# 黑板取值
# ---------------------------------------------------------------------------


class TestResolveReports:
    def test_board_priority_and_top_level_fallback(self):
        state = {
            "reports": {"market_report": "来自黑板"},
            "fundamentals_report": "来自顶层",
        }
        resolved = inputs_mod.resolve_reports(state, ["market_report", "fundamentals_report"])
        assert resolved == {"market_report": "来自黑板", "fundamentals_report": "来自顶层"}

    def test_missing_keys_omitted_in_enumeration_order(self):
        """缺键整段省略（= 现状动态收集语义），保留枚举序"""
        state = {"reports": {"b_report": "B", "a_report": "A"}}
        resolved = inputs_mod.resolve_reports(state, ["a_report", "ghost_report", "b_report"])
        assert list(resolved) == ["a_report", "b_report"]

    def test_empty_value_skipped(self):
        state = {"reports": {"market_report": ""}, "news_report": None}
        assert inputs_mod.resolve_reports(state, ["market_report", "news_report"]) == {}

    def test_all_upstream_reports(self):
        state = {"reports": {"a_report": "A", "b_report": ""}, "other": "x"}
        assert inputs_mod.all_upstream_reports(state) == {"a_report": "A"}


class TestResolveField:
    def test_nested_path(self):
        state = {"investment_debate_state": {"judge_decision": "裁决文本"}}
        assert inputs_mod.resolve_field(state, "investment_debate_state.judge_decision") == "裁决文本"

    def test_top_level_and_missing(self):
        state = {"final_trade_decision": "BUY"}
        assert inputs_mod.resolve_field(state, "final_trade_decision") == "BUY"
        assert inputs_mod.resolve_field(state, "investment_debate_state.judge_decision") is None
        assert inputs_mod.resolve_field(state, "a.b.c") is None

    def test_rounds_leaf_returns_raw_list(self):
        """rounds 叶子返回原始列表（消费方自行经派生视图格式化）"""
        state = {"risk_debate_state": {"rounds": [{"risky": "观点"}]}}
        assert inputs_mod.resolve_field(state, "risk_debate_state.rounds") == [{"risky": "观点"}]


class TestResolveInputs:
    def test_binding_forms(self):
        state = {
            "reports": {"market_report": "M", "news_report": "N"},
            "investment_debate_state": {"judge_decision": "J"},
            "trader_investment_plan": "P",
        }
        wiring = {
            "analyst_reports": ["market_report", "news_report"],
            "judge_decision": "investment_debate_state.judge_decision",
            "trader_plan": "trader_investment_plan",
            "single_report": "market_report",
            "all": "all_upstream",
        }
        resolved = inputs_mod.resolve_inputs(wiring, state)
        assert resolved["analyst_reports"] == {"market_report": "M", "news_report": "N"}
        assert resolved["judge_decision"] == "J"
        assert resolved["trader_plan"] == "P"
        assert resolved["single_report"] == "M"
        assert resolved["all"] == {"market_report": "M", "news_report": "N"}

    def test_missing_single_report_is_none(self):
        assert inputs_mod.resolve_inputs({"x": "ghost_report"}, {"reports": {}})["x"] is None


# ---------------------------------------------------------------------------
# 占位符渲染
# ---------------------------------------------------------------------------


class TestRenderTemplate:
    def test_scalar_and_missing_policy(self):
        slot = InputSlot.model_validate(
            {"slot": "judge_decision", "missing_policy": "暂无研究部主管裁决"}
        )
        text = "裁决：{{inputs.judge_decision}}；计划：{{inputs.trader_plan}}"
        rendered = inputs_mod.render_template(
            text,
            {"judge_decision": None, "trader_plan": "买入计划"},
            {"judge_decision": slot},
        )
        assert rendered == "裁决：暂无研究部主管裁决；计划：买入计划"

    def test_default_missing_text_without_contract(self):
        assert inputs_mod.render_template("{{inputs.x}}", {"x": None}) == inputs_mod.DEFAULT_MISSING_TEXT

    def test_report_bundle_uses_registry_titles(self):
        rendered = inputs_mod.render_template(
            "{{inputs.reports}}", {"reports": {"market_report": "内容X"}}
        )
        assert "市场技术" in rendered  # registry 中文名（非 key 原样）
        assert "内容X" in rendered
        assert "<report>" in rendered  # 边界符包裹

    def test_unknown_placeholder_preserved(self):
        assert inputs_mod.render_template("{{inputs.ghost}}", {}) == "{{inputs.ghost}}"

    def test_extract_placeholders(self):
        assert inputs_mod.extract_placeholders("{{inputs.a}} 然后 {{inputs.b_c}}") == ("a", "b_c")
        assert inputs_mod.extract_placeholders("无占位符") == ()


# ---------------------------------------------------------------------------
# required fail-fast（L263：市场技术 + 短线资金不可裁）
# ---------------------------------------------------------------------------


def _contracts_and_analyst_keys():
    """真实数据组装：契约来自种子库条目，分析师报告键来自 registry"""
    from app.engine.orchestrator import registry
    from app.engine.orchestrator.workflow.seeds import load_agent_seeds

    contracts = {
        e["spec"]["slug"]: e["spec"].get("template_inputs", []) for e in load_agent_seeds()
    }
    analyst_keys = {
        i.slug: tuple(i.report_keys)
        for i in registry._load_identities()
        if i.is_analyst
    }
    return contracts, analyst_keys


class TestRequiredSources:
    def test_full_selection_passes(self, seed_spec_from_loader):
        spec = seed_spec_from_loader
        params = CompileParams(selected_nodes=tuple(_contracts_and_analyst_keys()[1]))
        plan = compile_workflow(spec, params)
        contracts, analyst_keys = _contracts_and_analyst_keys()
        assert inputs_mod.check_required_sources(plan, spec, contracts, analyst_keys) == []

    def test_cutting_required_analyst_rejected(self, seed_spec_from_loader):
        """裁掉短线资金 → 辩手/trader 的 required_sources 失败（行为变更 L263）"""
        spec = seed_spec_from_loader
        params = CompileParams(selected_nodes=("market-analyst", "short-term-capital-analyst"))
        plan = compile_workflow(spec, params)
        contracts, analyst_keys = _contracts_and_analyst_keys()
        assert inputs_mod.check_required_sources(plan, spec, contracts, analyst_keys) == []

        # market 单选：market_report 在、short_term_capital_report 缺
        params_limited = CompileParams(selected_nodes=("market-analyst",))
        plan_limited = compile_workflow(spec, params_limited)
        errors = inputs_mod.check_required_sources(plan_limited, spec, contracts, analyst_keys)
        assert errors, "裁掉短线资金应触发 required 拒绝"
        assert any("'bull-researcher'" in e and "'short_term_capital_report'" in e for e in errors)
        assert any("'trader'" in e and "'short_term_capital_report'" in e for e in errors)

    def test_same_stage_output_cannot_satisfy(self, seed_spec_from_loader):
        """同阶段成员产出不可互相满足（辩论组输入 = 阶段开始时快照语义）"""
        spec = seed_spec_from_loader
        params = CompileParams(
            selected_nodes=("market-analyst", "short-term-capital-analyst"),
            stage_overrides={"research_debate": _override(enabled=True)},
        )
        plan = compile_workflow(spec, params)
        contracts, analyst_keys = _contracts_and_analyst_keys()
        # 注入伪造契约：bull-researcher 依赖 bear_researcher 的产出（同阶段）
        poisoned = dict(contracts)
        poisoned["bull-researcher"] = [
            {"slot": "analyst_reports", "required_sources": ["bear_researcher"]}
        ]
        errors = inputs_mod.check_required_sources(plan, spec, poisoned, analyst_keys)
        assert any("'bull-researcher'" in e and "'bear_researcher'" in e for e in errors)

    def test_disabled_optional_stage_field_not_required(self, seed_spec_from_loader):
        """phase2 关闭 → judge_decision 缺失由 missing_policy 降级，不触发 fail-fast"""
        spec = seed_spec_from_loader
        params = CompileParams(
            selected_nodes=("market-analyst", "short-term-capital-analyst"),
            stage_overrides={"research_debate": _override(enabled=False)},
        )
        plan = compile_workflow(spec, params)
        contracts, analyst_keys = _contracts_and_analyst_keys()
        assert inputs_mod.check_required_sources(plan, spec, contracts, analyst_keys) == []


def _override(enabled: bool) -> StageOverride:
    return StageOverride(enabled=enabled)


@pytest.fixture(scope="module")
def seed_spec_from_loader():
    from app.engine.orchestrator.workflow import loader

    spec, _ = loader.load_default_spec()
    return spec
