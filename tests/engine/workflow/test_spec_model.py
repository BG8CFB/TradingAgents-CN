"""WorkflowSpec 数据模型测试：schema 校验规则 + 种子可解析 + 誊抄锚点。

种子权威 = config/seeds/workflows.json（2026-09 DB 化，YAML 已退役）。
锚点断言（种子 nodes ↔ registry 静态段逐项一致）是 P2 防两处漂移的第一道验收；
运行时防线（validator 启动/编译校验）在 test_validator.py 覆盖。
"""

import pytest
from pydantic import ValidationError

from app.engine.orchestrator.workflow.seeds import load_workflow_seeds
from app.engine.orchestrator.workflow.spec import (
    CompileParams,
    DebateStage,
    InputSlot,
    NodeSpec,
    NodeType,
    NodeRef,
    ParallelBatchStage,
    SingleStage,
    StageOverride,
    WorkflowSpec,
    normalize_binding,
)


@pytest.fixture(scope="module")
def seed_spec() -> WorkflowSpec:
    """加载工作流种子（JSON，真实文件 I/O）→ WorkflowSpec"""
    raw = load_workflow_seeds()[0]
    return WorkflowSpec.model_validate(raw)


class TestSeedLoads:
    """种子 YAML 解析与结构"""

    def test_top_level_fields(self, seed_spec):
        assert seed_spec.version == 1
        assert seed_spec.slug == "default-4stage"
        assert seed_spec.name == "默认四阶段分析"
        assert seed_spec.enabled is True
        assert seed_spec.builtin is True

    def test_terminal_contract(self, seed_spec):
        t = seed_spec.terminal
        assert t.decision_field == "final_trade_decision"
        assert t.signal_fallback == (
            "final_trade_decision",
            "investment_plan",
            "risk_debate_state.judge_decision",
            "trader_investment_plan",
        )
        assert t.summary_node == "summary"

    def test_stage_order_and_types(self, seed_spec):
        stages = seed_spec.stages
        assert [s.id for s in stages] == [
            "analysts",
            "research_debate",
            "trader",
            "risk_debate",
            "summary",
        ]
        assert isinstance(stages[0], ParallelBatchStage)
        assert isinstance(stages[1], DebateStage)
        assert isinstance(stages[2], SingleStage)
        assert isinstance(stages[3], DebateStage)
        assert isinstance(stages[4], SingleStage)

    def test_analysts_stage_uses_phase1_pool(self, seed_spec):
        stage = seed_spec.stage_by_id("analysts")
        assert stage.pool is not None and stage.pool.value == "phase1_analysts"
        assert stage.nodes == ()
        assert stage.concurrency == 5

    def test_debate_stages_shape(self, seed_spec):
        research = seed_spec.stage_by_id("research_debate")
        assert research.optional is True
        assert research.state_key == "investment_debate_state"
        assert list(research.sides) == ["bull-researcher", "bear-researcher"]
        assert research.rounds == 1
        assert research.judge == "research-manager"

        risk = seed_spec.stage_by_id("risk_debate")
        assert risk.optional is True
        assert risk.state_key == "risk_debate_state"
        assert list(risk.sides) == ["risky-analyst", "safe-analyst", "neutral-analyst"]
        assert risk.rounds == 1
        assert risk.judge == "risk-manager"

    def test_single_stages_not_optional(self, seed_spec):
        # trader/summary 恒执行（analysts 池阶段同样不可关）
        for stage_id in ("trader", "summary", "analysts"):
            assert seed_spec.stage_by_id(stage_id).optional is False


class TestSeedRegistryAnchor:
    """种子 nodes ↔ P1 registry 静态段逐项一致（防誊抄漂移锚点）"""

    def _static_identities(self):
        from app.engine.orchestrator import registry

        return [i for i in registry._load_identities() if not i.is_analyst]

    def test_node_slug_set_matches_registry(self, seed_spec):
        reg_slugs = {i.slug for i in self._static_identities()}
        seed_slugs = {n.slug for n in seed_spec.nodes}
        assert seed_slugs == reg_slugs

    @pytest.mark.parametrize(
        "slug,type_,memory,node_name,event_key,report_keys,terminal",
        [
            (
                "bull-researcher",
                NodeType.DEBATER,
                "bull",
                "Bull Researcher",
                "researcher_bull",
                ("bull_researcher",),
                False,
            ),
            (
                "bear-researcher",
                NodeType.DEBATER,
                "bear",
                "Bear Researcher",
                "researcher_bear",
                ("bear_researcher",),
                False,
            ),
            (
                "research-manager",
                NodeType.JUDGE,
                "invest_judge",
                "Research Manager",
                "research_manager",
                ("research_team_decision",),
                False,
            ),
            (
                "trader",
                NodeType.TRADER,
                "trader",
                "Trader",
                "trader",
                ("trader_investment_plan", "investment_plan", "final_trade_decision"),
                False,
            ),
            ("risky-analyst", NodeType.DEBATER, None, "Risky Analyst", "risk_debater_risky", ("risky_analyst",), False),
            ("safe-analyst", NodeType.DEBATER, None, "Safe Analyst", "risk_debater_safe", ("safe_analyst",), False),
            (
                "neutral-analyst",
                NodeType.DEBATER,
                None,
                "Neutral Analyst",
                "risk_debater_neutral",
                ("neutral_analyst",),
                False,
            ),
            (
                "risk-manager",
                NodeType.JUDGE,
                "risk_manager",
                "Risk Judge",
                "risk_manager",
                ("risk_management_decision", "risk_manager_decision"),
                True,
            ),
            ("summary", NodeType.SUMMARIZER, None, "Summary Agent", "summary", (), False),
        ],
    )
    def test_node_fields_match_registry_literal(
        self, seed_spec, slug, type_, memory, node_name, event_key, report_keys, terminal
    ):
        node = seed_spec.node_by_slug(slug)
        assert node is not None, f"种子缺少节点 {slug}"
        assert node.type == type_
        assert node.memory == memory
        assert node.execution.value == "single_turn"  # Stage 2-4 现状全部单轮
        assert node.node_name == node_name
        assert node.event_key == event_key
        assert tuple(node.report_keys) == report_keys
        assert node.terminal is terminal
        assert node.builtin is True

    def test_stage_refs_resolve_in_nodes(self, seed_spec):
        """辩论 sides/judge 与 single node 的 ref 全部命中 nodes 库"""
        slugs = {n.slug for n in seed_spec.nodes}
        for stage in seed_spec.stages:
            if isinstance(stage, DebateStage):
                assert set(stage.sides) <= slugs, f"{stage.id} sides 未命中库"
                assert stage.judge in slugs
            elif isinstance(stage, SingleStage):
                assert stage.node in slugs

    def test_terminal_field_writer_exists(self, seed_spec):
        """decision_field 的写入者 = 标记 terminal 的节点（risk-manager 兼任）"""
        terminal_nodes = [n for n in seed_spec.nodes if n.terminal]
        assert [n.slug for n in terminal_nodes] == ["risk-manager"]


class TestModelValidation:
    """schema 校验规则：非法值拒绝"""

    def _node_kwargs(self, **overrides):
        base = dict(
            slug="x-node",
            type="judge",
            execution="single_turn",
            node_name="X Node",
            event_key="x_node",
        )
        base.update(overrides)
        return base

    def test_reject_unknown_type(self):
        with pytest.raises(ValidationError):
            NodeSpec.model_validate(self._node_kwargs(type="oracle"))

    def test_reject_unknown_memory_slot(self):
        with pytest.raises(ValidationError):
            NodeSpec.model_validate(self._node_kwargs(memory="psychic"))

    def test_reject_rounds_out_of_range(self):
        with pytest.raises(ValidationError):
            DebateStage(id="d", state_key="s", sides=["a", "b"], judge="j", rounds=11)
        with pytest.raises(ValidationError):
            DebateStage(id="d", state_key="s", sides=["a", "b"], judge="j", rounds=-1)

    def test_reject_unknown_stage_mode(self):
        with pytest.raises(ValidationError):
            WorkflowSpec.model_validate(
                dict(
                    slug="w",
                    name="w",
                    terminal=dict(decision_field="d", summary_node="s"),
                    stages=[dict(id="x", mode="quantum")],
                )
            )

    def test_reject_unknown_pool(self):
        with pytest.raises(ValidationError):
            ParallelBatchStage(id="p", pool="phase2_oracles")

    def test_reject_concurrency_below_one(self):
        with pytest.raises(ValidationError):
            ParallelBatchStage(id="p", concurrency=0)

    def test_models_are_frozen(self, seed_spec):
        with pytest.raises(ValidationError):
            seed_spec.enabled = False
        node = seed_spec.nodes[0]
        with pytest.raises(ValidationError):
            node.slug = "mutated"

    def test_stage_discriminator_roundtrip(self):
        """mode 判别：parallel_batch/debate/single 各自实例化为对应类型"""
        spec = WorkflowSpec.model_validate(
            dict(
                slug="w",
                name="w",
                terminal=dict(decision_field="d", summary_node="s"),
                stages=[
                    dict(id="a", mode="parallel_batch", nodes=[{"ref": "x"}]),
                    dict(id="d", mode="debate", state_key="k", sides=["a", "b"], judge="j"),
                    dict(id="s", mode="single", node="n"),
                ],
            )
        )
        assert isinstance(spec.stages[0], ParallelBatchStage)
        assert isinstance(spec.stages[1], DebateStage)
        assert isinstance(spec.stages[2], SingleStage)
        assert spec.stages[0].nodes[0].ref == "x"

    def test_compile_params_defaults(self):
        params = CompileParams()
        assert params.selected_nodes == ()
        assert params.stage_overrides == {}
        override = StageOverride(enabled=False, rounds=3)
        assert override.enabled is False and override.rounds == 3

    def test_node_ref_defaults(self):
        ref = NodeRef(ref="market")
        assert ref.default_selected is None
        assert ref.inputs == {}

    def test_input_slot_contract_shape(self):
        """InputSlot 契约条目：required_sources 表达「槽内必须解析成功的来源键」"""
        slot = InputSlot.model_validate(
            {
                "slot": "analyst_reports",
                "required_sources": ["market_report", "short_term_capital_report"],
            }
        )
        assert slot.required is False
        assert slot.required_sources == ("market_report", "short_term_capital_report")
        assert slot.missing_policy == ""

        fallback = InputSlot.model_validate(
            {"slot": "judge_decision", "missing_policy": "暂无研究部主管裁决"}
        )
        assert fallback.required_sources == ()

    def test_normalize_binding_forms(self):
        assert normalize_binding("market_report") == ("market_report",)
        assert normalize_binding(["a_report", "b_report"]) == ("a_report", "b_report")
        assert normalize_binding([]) == ()

    def test_stage_inputs_parse(self, seed_spec):
        """三类 stage 的 inputs 字段解析（str 点路径 / list 报告键集合）"""
        trader = seed_spec.stage_by_id("trader")
        assert isinstance(trader.inputs["analyst_reports"], list)
        assert isinstance(trader.inputs["judge_decision"], str)
        # pool 阶段无组级连线：分析师为源头节点，连线只能落在 NodeRef.inputs
        assert seed_spec.stage_by_id("analysts").nodes == ()
