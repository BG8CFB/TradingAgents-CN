"""loader / validator 测试：DB/种子装配真实 I/O + 全部校验规则（含锚点漂移注入）。

校验器测试通过 pydantic 构造 spec 变体（真实对象构造，非 mock）；种子锚点对
registry 的对照是真实 I/O（智能体库经 store 真实读取）。
"""

import pytest
from pydantic import ValidationError as PydanticValidationError

from app.engine.orchestrator.workflow import loader, validator
from app.engine.orchestrator.workflow.spec import (
    DebateStage,
    NodeSpec,
    NodeType,
    ParallelBatchStage,
    SingleStage,
    WorkflowSpec,
    normalize_binding,
)

_ = (DebateStage, ParallelBatchStage, SingleStage)  # 结构类型供扩展使用

pytestmark = pytest.mark.requires_db


@pytest.fixture(scope="module")
def seed_spec() -> WorkflowSpec:
    spec, _ = loader.load_default_spec()
    return spec


@pytest.fixture
def cache_cleared():
    loader.clear_workflow_cache()
    yield
    loader.clear_workflow_cache()


# ---------------------------------------------------------------------------
# loader
# ---------------------------------------------------------------------------


class TestLoader:
    def test_load_default_spec(self, cache_cleared, seed_spec):
        assert seed_spec.slug == loader.DEFAULT_WORKFLOW_SLUG

    def test_fingerprint_stable_per_content(self, cache_cleared):
        _, fp1 = loader.load_default_spec()
        _, fp2 = loader.load_default_spec()
        assert fp1 == fp2 and fp1.startswith("sha256:")

    def test_same_content_reuses_instance(self, cache_cleared):
        spec1, _ = loader.load_default_spec()
        spec2, _ = loader.load_default_spec()
        assert spec1 is spec2  # spec_hash 未变命中模型缓存（frozen，共享安全）

    def test_unknown_slug_raises(self):
        with pytest.raises(loader.WorkflowLoadError):
            loader.load_workflow_by_slug("nonexistent-workflow")


# ---------------------------------------------------------------------------
# validator：种子本身全绿
# ---------------------------------------------------------------------------


class TestSeedValidates:
    def test_seed_passes_all(self, seed_spec):
        assert validator.validate(seed_spec) == []
        assert validator.validate_registry_anchor(seed_spec) == []
        validator.validate_or_raise(seed_spec)  # 不抛


# ---------------------------------------------------------------------------
# validator：结构规则（构造 spec 变体验证拒绝与错误定位）
# ---------------------------------------------------------------------------


def _node(slug: str, type_: str = "debater", **overrides) -> dict:
    base = dict(
        slug=slug,
        type=type_,
        execution="tool_loop" if type_ == "analyst" else "single_turn",
        node_name=slug.replace("-", " ").title(),
        event_key=slug.replace("-", "_"),
        report_keys=[f"{slug.replace('-', '_')}_out"],
    )
    base.update(overrides)
    return base


def _spec(nodes, stages, **overrides) -> WorkflowSpec:
    raw = dict(
        slug="test-wf",
        name="test",
        terminal=dict(decision_field="final_decision", summary_node="sum"),
        nodes=nodes,
        stages=stages,
    )
    raw.update(overrides)
    return WorkflowSpec.model_validate(raw)


class TestStructuralRules:
    def test_duplicate_stage_id(self):
        spec = _spec(
            [_node("a"), _node("b"), _node("j", "judge"), _node("sum", "summarizer")],
            [
                dict(id="x", mode="single", node="sum"),
                dict(id="x", mode="single", node="sum"),
            ],
        )
        errors = validator.validate(spec)
        assert any("id 重复" in e and "x" in e for e in errors)

    def test_debate_needs_two_sides(self):
        spec = _spec(
            [_node("solo"), _node("j", "judge"), _node("sum", "summarizer")],
            [
                dict(id="d", mode="debate", state_key="k", sides=["solo"], judge="j"),
                dict(id="s", mode="single", node="sum"),
            ],
        )
        errors = validator.validate(spec)
        assert any("sides" in e and "至少 2 方" in e for e in errors)

    def test_debate_side_must_be_in_library(self):
        spec = _spec(
            [_node("a"), _node("b"), _node("j", "judge"), _node("sum", "summarizer")],
            [
                dict(id="d", mode="debate", state_key="k", sides=["a", "ghost"], judge="j"),
                dict(id="s", mode="single", node="sum"),
            ],
        )
        errors = validator.validate(spec)
        assert any("sides[1]" in e and "ghost" in e for e in errors)

    def test_judge_type_mismatch(self):
        spec = _spec(
            [_node("a"), _node("b"), _node("j", "debater"), _node("sum", "summarizer")],
            [
                dict(id="d", mode="debate", state_key="k", sides=["a", "b"], judge="j"),
                dict(id="s", mode="single", node="sum"),
            ],
        )
        errors = validator.validate(spec)
        assert any("judge" in e and "不是 judge/terminal" in e for e in errors)

    def test_judge_cannot_be_side(self):
        spec = _spec(
            [_node("a"), _node("j", "judge"), _node("sum", "summarizer")],
            [
                dict(id="d", mode="debate", state_key="k", sides=["a", "j"], judge="j"),
                dict(id="s", mode="single", node="sum"),
            ],
        )
        errors = validator.validate(spec)
        assert any("不能同时是辩手" in e for e in errors)

    def test_debater_must_be_single_turn(self):
        with pytest.raises(PydanticValidationError):
            NodeSpec.model_validate(_node("evil-debater", execution="tool_loop"))

    def test_duplicate_report_key(self):
        spec = _spec(
            [
                _node("a", report_keys=["shared_key"]),
                _node("b", report_keys=["shared_key"]),
                _node("j", "judge"),
                _node("sum", "summarizer"),
            ],
            [
                dict(id="d", mode="debate", state_key="k", sides=["a", "b"], judge="j"),
                dict(id="s", mode="single", node="sum"),
            ],
        )
        errors = validator.validate(spec)
        assert any("report_key 'shared_key'" in e for e in errors)

    def test_batch_nodes_and_pool_exclusive(self):
        spec = _spec(
            [_node("market", "analyst"), _node("sum", "summarizer")],
            [
                dict(
                    id="p",
                    mode="parallel_batch",
                    pool="phase1_analysts",
                    nodes=[{"ref": "market"}],
                ),
                dict(id="s", mode="single", node="sum"),
            ],
        )
        errors = validator.validate(spec)
        assert any("nodes 与 pool 必须二选一" in e for e in errors)

    def test_batch_ref_must_resolve(self):
        spec = _spec(
            [_node("sum", "summarizer")],
            [
                dict(id="p", mode="parallel_batch", nodes=[{"ref": "market"}]),
                dict(id="s", mode="single", node="sum"),
            ],
        )
        errors = validator.validate(spec)
        # market 不在 nodes 库，但命中 phase1（真实 YAML 有 market-analyst → slug 检查用全 slug）
        # 此处 ref="market" 非 slug → 未命中
        assert any("nodes[0]" in e and "market" in e for e in errors)

    def test_batch_phase1_slug_resolves(self):
        """ref 用真实 phase1 slug（market-analyst）应通过"""
        spec = _spec(
            [_node("sum", "summarizer"), _node("decide", "terminal", terminal=True)],
            [
                dict(id="p", mode="parallel_batch", nodes=[{"ref": "market-analyst"}]),
                dict(id="s", mode="single", node="sum"),
            ],
        )
        errors = validator.validate(spec)
        assert errors == []

    def test_single_node_must_resolve(self):
        spec = _spec([_node("sum", "summarizer")], [dict(id="s", mode="single", node="ghost")])
        errors = validator.validate(spec)
        assert any("node: 'ghost' 未命中" in e for e in errors)

    def test_no_terminal_writer(self):
        spec = _spec(
            [_node("a"), _node("b"), _node("j", "judge"), _node("sum", "summarizer")],
            [
                dict(id="d", mode="debate", state_key="k", sides=["a", "b"], judge="j"),
                dict(id="s", mode="single", node="sum"),
            ],
        )
        errors = validator.validate(spec)
        assert any("无 terminal: true 节点" in e for e in errors)

    def test_terminal_flag_on_wrong_type(self):
        spec = _spec(
            [
                _node("a", terminal=True),
                _node("b"),
                _node("j", "judge", terminal=True),
                _node("sum", "summarizer"),
            ],
            [
                dict(id="d", mode="debate", state_key="k", sides=["a", "b"], judge="j"),
                dict(id="s", mode="single", node="sum"),
            ],
        )
        errors = validator.validate(spec)
        assert any("terminal 标记只允许 judge/terminal" in e and "'a'" in e for e in errors)

    def test_summary_node_must_resolve(self):
        spec = _spec(
            [_node("a"), _node("b"), _node("j", "judge"), _node("sum", "summarizer")],
            [dict(id="d", mode="debate", state_key="k", sides=["a", "b"], judge="j")],
            terminal=dict(decision_field="final_decision", summary_node="ghost"),
        )
        errors = validator.validate(spec)
        assert any("summary_node" in e and "ghost" in e for e in errors)

    def test_validate_or_raise_aggregates(self):
        spec = _spec([_node("sum", "summarizer")], [dict(id="s", mode="single", node="ghost")])
        with pytest.raises(validator.WorkflowValidationError) as exc_info:
            validator.validate_or_raise(spec, check_anchor=False)
        assert len(exc_info.value.errors) >= 2  # single 未命中 + summary 未命中


# ---------------------------------------------------------------------------
# validator：registry 锚点（漂移注入）
# ---------------------------------------------------------------------------


class TestRegistryAnchor:
    def test_node_name_drift_detected(self, seed_spec):
        drifted = seed_spec.model_copy(
            update={
                "nodes": tuple(
                    n.model_copy(update={"node_name": "Mutated Researcher"}) if n.slug == "research-manager" else n
                    for n in seed_spec.nodes
                )
            }
        )
        errors = validator.validate_registry_anchor(drifted)
        assert any("research-manager" in e and "node_name" in e for e in errors)

    def test_report_keys_drift_detected(self, seed_spec):
        drifted = seed_spec.model_copy(
            update={
                "nodes": tuple(
                    n.model_copy(update={"report_keys": ("bear_researcher",)}) if n.slug == "bull-researcher" else n
                    for n in seed_spec.nodes
                )
            }
        )
        errors = validator.validate_registry_anchor(drifted)
        assert any("bull-researcher" in e and "report_keys" in e for e in errors)

    def test_missing_node_detected(self, seed_spec):
        drifted = seed_spec.model_copy(update={"nodes": tuple(n for n in seed_spec.nodes if n.slug != "summary")})
        errors = validator.validate_registry_anchor(drifted)
        assert any("缺失于种子" in e and "summary" in e for e in errors)

    def test_extra_node_detected(self, seed_spec):
        extra = NodeSpec.model_validate(
            dict(slug="oracle-node", type="judge", execution="single_turn", node_name="Oracle", event_key="oracle")
        )
        drifted = seed_spec.model_copy(update={"nodes": seed_spec.nodes + (extra,)})
        errors = validator.validate_registry_anchor(drifted)
        assert any("不存在于 registry" in e and "oracle-node" in e for e in errors)

    def test_type_drift_detected(self, seed_spec):
        drifted = seed_spec.model_copy(
            update={
                "nodes": tuple(
                    n.model_copy(update={"type": NodeType.DEBATER}) if n.slug == "trader" else n
                    for n in seed_spec.nodes
                )
            }
        )
        errors = validator.validate_registry_anchor(drifted)
        assert any("trader" in e and "type" in e for e in errors)


# ---------------------------------------------------------------------------
# validator：输入连线（P3）——可达性 / all_upstream 限制 / 槽覆盖
# ---------------------------------------------------------------------------

SIX_ANALYST_KEYS = [
    "market_report",
    "financial_news_report",
    "china_market_report",
    "social_media_report",
    "fundamentals_report",
    "short_term_capital_report",
]


class TestSeedInputWiring:
    """内置种子逐槽显式枚举（L261 等价行为锁定 + L263 required 正式化）"""

    def test_seed_wiring_parses(self, seed_spec):
        research = seed_spec.stage_by_id("research_debate")
        assert set(research.inputs) == {"analyst_reports"}
        assert normalize_binding(research.inputs["analyst_reports"]) == tuple(SIX_ANALYST_KEYS)

        trader = seed_spec.stage_by_id("trader")
        assert trader.inputs["judge_decision"] == "investment_debate_state.judge_decision"

        risk = seed_spec.stage_by_id("risk_debate")
        # stage-3 现状真实输入集 = 6 分析师报告 + stage-2 产物（collect_reports 无黑名单排除）
        assert normalize_binding(risk.inputs["analyst_reports"]) == tuple(
            SIX_ANALYST_KEYS + ["bull_researcher", "bear_researcher", "research_team_decision"]
        )
        assert risk.inputs["trader_plan"] == "trader_investment_plan"

        summary = seed_spec.stage_by_id("summary")
        assert summary.inputs["final_decision"] == "final_trade_decision"
        # P3-f：绑定 debate_state 整体（派生视图 risk_history 在节点内做，非点路径）
        assert summary.inputs["risk_debate_history"] == "risk_debate_state"

    def test_seed_contracts_carry_required_sources(self):
        from app.engine.orchestrator.workflow.seeds import load_agent_seeds

        by_slug = {e["spec"]["slug"]: e["spec"] for e in load_agent_seeds()}
        # L263：市场技术 + 短线资金为辩手/trader 的 required 槽（裁掉即拒绝任务）
        for slug in ("bull-researcher", "bear-researcher", "trader", "risky-analyst"):
            slots = {c["slot"]: c for c in by_slug[slug]["template_inputs"]}
            assert slots["analyst_reports"]["required_sources"] == [
                "market_report",
                "short_term_capital_report",
            ], slug
        # trader 的 judge_decision 兜底文案 = 现有降级模式的泛化
        trader_slots = {c["slot"]: c for c in by_slug["trader"]["template_inputs"]}
        assert trader_slots["judge_decision"]["missing_policy"] == "暂无研究部主管裁决"


class TestInputWiringRules:
    def _wired_spec(self, *, builtin=False, stages=None) -> WorkflowSpec:
        nodes = [
            _node("a"),
            _node("b"),
            _node("j", "judge"),
            _node("sum", "summarizer"),
            _node("dec", "terminal", terminal=True),  # decision_field 写入者（结构校验要求）
        ]
        default_stages = [
            dict(
                id="d",
                mode="debate",
                state_key="k",
                sides=["a", "b"],
                judge="j",
            ),
            dict(id="s", mode="single", node="sum"),
        ]
        return _spec(nodes, stages if stages is not None else default_stages, builtin=builtin)

    def test_binding_to_unknown_key_rejected(self):
        spec = self._wired_spec(
            stages=[
                dict(id="d", mode="debate", state_key="k", sides=["a", "b"], judge="j"),
                dict(
                    id="s",
                    mode="single",
                    node="sum",
                    inputs={"analyst_reports": ["a_out", "ghost_report"]},
                ),
            ]
        )
        errors = validator.validate(spec)
        assert any("inputs.analyst_reports" in e and "'ghost_report'" in e for e in errors)

    def test_forward_reference_rejected(self):
        """阶段不可引用自身或其后阶段产出（辩论产物对组内自己不可见）"""
        spec = self._wired_spec(
            stages=[
                dict(
                    id="d",
                    mode="debate",
                    state_key="k",
                    sides=["a", "b"],
                    judge="j",
                    inputs={"context": "sum_out"},  # sum 在本阶段之后执行
                ),
                dict(id="s", mode="single", node="sum"),
            ]
        )
        errors = validator.validate(spec)
        assert any("inputs.context" in e and "'sum_out'" in e for e in errors)

    def test_field_path_via_debate_state_root(self):
        spec = self._wired_spec(
            stages=[
                dict(
                    id="d",
                    mode="debate",
                    state_key="k",
                    sides=["a", "b"],
                    judge="j",
                ),
                dict(
                    id="s",
                    mode="single",
                    node="sum",
                    inputs={"verdict": "k.judge_decision", "rounds": "k.rounds"},
                ),
            ]
        )
        assert validator.validate(spec) == []

    def test_unknown_state_root_rejected(self):
        spec = self._wired_spec(
            stages=[
                dict(id="d", mode="debate", state_key="k", sides=["a", "b"], judge="j"),
                dict(
                    id="s",
                    mode="single",
                    node="sum",
                    inputs={"verdict": "other_state.judge_decision"},
                ),
            ]
        )
        errors = validator.validate(spec)
        assert any("inputs.verdict" in e and "'other_state.judge_decision'" in e for e in errors)

    def test_all_upstream_allowed_for_custom(self):
        spec = self._wired_spec(
            stages=[
                dict(id="d", mode="debate", state_key="k", sides=["a", "b"], judge="j"),
                dict(
                    id="s",
                    mode="single",
                    node="sum",
                    inputs={"context": "all_upstream"},
                ),
            ],
            builtin=False,
        )
        assert validator.validate(spec) == []

    def test_all_upstream_rejected_for_builtin(self):
        spec = self._wired_spec(
            stages=[
                dict(id="d", mode="debate", state_key="k", sides=["a", "b"], judge="j"),
                dict(
                    id="s",
                    mode="single",
                    node="sum",
                    inputs={"context": "all_upstream"},
                ),
            ],
            builtin=True,
        )
        errors = validator.validate(spec)
        assert any("禁用 all_upstream" in e for e in errors)

    def test_batch_node_ref_inputs_reachability(self):
        """parallel_batch 成员 NodeRef.inputs 同样参与可达性校验"""
        spec = self._wired_spec(
            stages=[
                dict(
                    id="p",
                    mode="parallel_batch",
                    nodes=[{"ref": "market-analyst", "inputs": {"upstream": "a_out"}}],
                ),
                dict(id="d", mode="debate", state_key="k", sides=["a", "b"], judge="j"),
                dict(id="s", mode="single", node="sum"),
            ],
        )
        # a_out 由 debate 阶段产出，晚于 parallel_batch → 不可达
        errors = validator.validate(spec)
        assert any("nodes[0] (market-analyst).inputs.upstream" in e for e in errors)

    def test_coverage_missing_slot_reported(self):
        spec = self._wired_spec(
            stages=[
                dict(id="d", mode="debate", state_key="k", sides=["a", "b"], judge="j"),
                dict(
                    id="s",
                    mode="single",
                    node="sum",
                    inputs={"only_one": "a_out"},
                ),
            ]
        )
        contracts = {
            "sum": [{"slot": "analyst_reports"}, {"slot": "trader_plan"}],
            "a": [{"slot": "analyst_reports"}],
        }
        errors = validator.validate_inputs_coverage(spec, contracts)
        # sum 的 trader_plan 未连线；辩论组输入未覆盖 a 的 analyst_reports
        assert any("'sum'" in e and "'trader_plan'" in e for e in errors)
        assert any("'a'" in e and "'analyst_reports'" in e for e in errors)

    def test_coverage_via_group_inputs(self):
        spec = self._wired_spec(
            stages=[
                dict(
                    id="d",
                    mode="debate",
                    state_key="k",
                    sides=["a", "b"],
                    judge="j",
                    inputs={"analyst_reports": "sum_out"},  # 覆盖性只看槽名（可达性另有校验）
                ),
                dict(id="s", mode="single", node="sum"),
            ]
        )
        contracts = {
            "a": [{"slot": "analyst_reports"}],
            "b": [{"slot": "analyst_reports"}],
            "j": [{"slot": "analyst_reports"}],
        }
        assert validator.validate_inputs_coverage(spec, contracts) == []

    def test_coverage_skips_nodes_without_contract(self):
        spec = self._wired_spec()
        assert validator.validate_inputs_coverage(spec, {}) == []
