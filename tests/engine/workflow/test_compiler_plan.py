"""compiler / CompiledPlan 测试：纯函数编译（无 LLM 无 deps）。

- 四场景编译形状对照（golden 四场景的编译期镜像：阶段序/身份/相位/轮数）
- total_units 七组计数断言（批次/辩论/单节点等权公式）
- params_from_legacy_config 兼容映射（旧 API 契约 → CompileParams）
- 编译期校验拒绝路径（非 optional 关闭 / 未知视图 / 未知节点 / 子集化空批）
"""

import pytest

from app.engine.orchestrator.workflow.compiler import (
    CompileError,
    compile_workflow,
    params_from_legacy_config,
)
from app.engine.orchestrator.workflow.loader import load_default_spec
from app.engine.orchestrator.workflow.plan import PlannedBatch, PlannedDebate, PlannedSingle
from app.engine.orchestrator.workflow.spec import CompileParams, StageOverride

pytestmark = pytest.mark.requires_db


@pytest.fixture(scope="module")
def spec():
    return load_default_spec()[0]


def _stage_summary(plan):
    """plan → 可对照的有序摘要（batch slugs / debate 身份 / single 指令）"""
    out = []
    for st in plan.stages:
        if isinstance(st, PlannedBatch):
            out.append(("batch", st.event_phase, list(st.slugs), st.concurrency))
        elif isinstance(st, PlannedDebate):
            out.append(
                (
                    "debate",
                    st.event_phase,
                    st.state_key,
                    [n.node_name for n in st.sides],
                    st.judge.node_name,
                    st.rounds,
                    st.report_view,
                )
            )
        elif isinstance(st, PlannedSingle):
            out.append(("single", st.event_phase, st.node.node_name, st.node.event_key, st.node.critical))
    return out


class TestScenarioCompile:
    """四场景编译形状（与 golden 执行场景一一对应）"""

    def test_g1_full_topology(self, spec):
        params = params_from_legacy_config(
            {"phase2_enabled": True, "phase3_enabled": True, "phase2_debate_rounds": 1, "phase3_debate_rounds": 1},
            ["market-analyst", "news-analyst"],
        )
        plan = compile_workflow(spec, params)
        assert _stage_summary(plan) == [
            ("batch", "analysts", ["market-analyst", "news-analyst"], 5),
            (
                "debate",
                "research",
                "investment_debate_state",
                ["Bull Researcher", "Bear Researcher"],
                "Research Manager",
                1,
                "investment",
            ),
            ("single", "trader", "Trader", "trader", True),
            (
                "debate",
                "risk",
                "risk_debate_state",
                ["Risky Analyst", "Safe Analyst", "Neutral Analyst"],
                "Risk Judge",
                1,
                "risk",
            ),
            ("single", "summary", "Summary Agent", "summary", True),
        ]

    def test_g2_phase2_only(self, spec):
        plan = compile_workflow(
            spec, params_from_legacy_config({"phase2_enabled": True, "phase3_enabled": False}, ["market-analyst"])
        )
        phases = [s[1] for s in _stage_summary(plan)]
        assert phases == ["analysts", "research", "trader", "summary"]

    def test_g3_phase3_only(self, spec):
        plan = compile_workflow(
            spec, params_from_legacy_config({"phase2_enabled": False, "phase3_enabled": True}, ["market-analyst"])
        )
        phases = [s[1] for s in _stage_summary(plan)]
        assert phases == ["analysts", "trader", "risk", "summary"]

    def test_g4_analyst_subset_preserves_order(self, spec):
        plan = compile_workflow(
            spec,
            params_from_legacy_config(
                {"phase2_enabled": True, "phase3_enabled": True}, ["social-media-analyst", "market-analyst"]
            ),
        )
        batch = _stage_summary(plan)[0]
        assert batch[2] == ["social-media-analyst", "market-analyst"]  # 提交序保持


class TestTotalUnits:
    """total_units 等权计数公式（批次节点数 + 辩论 sides×(rounds+1)+judge + 单节点）

    期望数字为旧 compute_total_units 的历史参考值（函数已随编排重写删除；
    数字含义：分析师数 + [2 方×(r+1)+1] + 1 Trader + [3 方×(r+1)+1] + 1 Summary）
    """

    def _plan(self, *, phase2, r2, phase3, r3):
        spec = load_default_spec()[0]
        params = params_from_legacy_config(
            {
                "phase2_enabled": phase2,
                "phase3_enabled": phase3,
                "phase2_debate_rounds": r2,
                "phase3_debate_rounds": r3,
            },
            ["market-analyst"],
        )
        return compile_workflow(spec, params)

    def test_analysts_only(self):
        plan = self._plan(phase2=False, r2=1, phase3=False, r3=1)
        assert plan.total_units(4) == 6  # 4 + 1 + 1

    def test_phase2_only_rounds_1(self):
        plan = self._plan(phase2=True, r2=1, phase3=False, r3=0)
        assert plan.total_units(4) == 11  # 4 + 5 + 1 + 1

    def test_phase3_only_rounds_1(self):
        plan = self._plan(phase2=False, r2=0, phase3=True, r3=1)
        assert plan.total_units(2) == 11  # 2 + 1 + 7 + 1

    def test_phase2_and_phase3(self):
        plan = self._plan(phase2=True, r2=1, phase3=True, r3=1)
        assert plan.total_units(3) == 17  # 3 + 5 + 1 + 7 + 1

    def test_rounds_0_still_runs_once(self):
        plan = self._plan(phase2=True, r2=0, phase3=False, r3=0)
        assert plan.total_units(1) == 6  # 1 + 3 + 1 + 1

    def test_negative_rounds_clamped_at_compile(self):
        """负轮次在编译期 clamp 到 0（1 轮发言），与 rounds=0 计数一致"""
        plan = self._plan(phase2=True, r2=-3, phase3=False, r3=0)
        assert plan.total_units(1) == 6

    def test_runtime_analyst_count_correction(self):
        """analyst_count 运行时修正（装配层跳过无效 slug 后的回填）优先于编译期 slugs 数"""
        plan = self._plan(phase2=False, r2=1, phase3=False, r3=1)
        assert plan.total_units(0) == 2  # 0 分析师防御：Trader + Summary
        assert plan.total_units() == 3  # 缺省 = 编译期 slugs 数（1 个选中）


class TestLegacyParams:
    """params_from_legacy_config 兼容映射（旧 API 契约单点承接）"""

    def test_defaults_disabled(self):
        params = params_from_legacy_config({}, ["market-analyst"])
        assert params.selected_nodes == ("market-analyst",)
        assert params.stage_overrides["research_debate"].enabled is False
        assert params.stage_overrides["risk_debate"].enabled is False

    def test_rounds_fallback_chain(self):
        params = params_from_legacy_config({"max_debate_rounds": 2}, [])
        assert params.stage_overrides["research_debate"].rounds == 2
        params = params_from_legacy_config(
            {"max_debate_rounds": 2, "phase2_debate_rounds": 3, "max_risk_discuss_rounds": 4}, []
        )
        assert params.stage_overrides["research_debate"].rounds == 3  # 显式键优先
        assert params.stage_overrides["risk_debate"].rounds == 4

    def test_rounds_clamped_at_compile(self, spec):
        params = params_from_legacy_config({"phase2_enabled": True, "phase2_debate_rounds": 99}, ["market-analyst"])
        debate = [s for s in compile_workflow(spec, params).stages if isinstance(s, PlannedDebate)][0]
        assert debate.rounds == 10  # MAX_ROUNDS clamp（与旧 pipeline 行为一致）

    def test_analyst_concurrency_override(self, spec):
        params = params_from_legacy_config({"analyst_concurrency": 3}, ["market-analyst"])
        batch = compile_workflow(spec, params).stages[0]
        assert batch.concurrency == 3

    def test_unknown_override_ignored(self, spec):
        """未知 stage id 的 override（自定义工作流场景）忽略不报错"""
        params = CompileParams(
            selected_nodes=("market-analyst",),
            stage_overrides={"ghost_stage": StageOverride(enabled=False)},
        )
        plan = compile_workflow(spec, params)
        assert len(plan.stages) == 5

    def test_explicit_stage_overrides_field_level_merge(self, spec):
        """P5-c：config['stage_overrides'] 按字段级优先覆盖 legacy phaseN_* 映射"""
        config = {
            "phase2_enabled": True,
            "phase2_debate_rounds": 2,
            "phase3_enabled": False,
            "stage_overrides": {
                # 覆盖 legacy 键：只改 rounds，enabled 继承 phase2_enabled=True
                "research_debate": {"rounds": 5},
                # legacy 未映射的自定义 stage_id 直通
                "custom_stage": {"enabled": True, "concurrency": 2},
            },
        }
        params = params_from_legacy_config(config, ["market-analyst"])
        assert params.stage_overrides["research_debate"].rounds == 5
        assert params.stage_overrides["research_debate"].enabled is True  # 字段级合并保留
        assert params.stage_overrides["risk_debate"].enabled is False
        assert params.stage_overrides["custom_stage"].enabled is True
        assert params.stage_overrides["custom_stage"].concurrency == 2

        # 编译链路端到端：显式 rounds 进 plan
        debate = [s for s in compile_workflow(spec, params).stages if isinstance(s, PlannedDebate)][0]
        assert debate.rounds == 5

    def test_explicit_stage_overrides_none_and_malformed_skipped(self):
        """None 字段不覆盖 legacy 映射；非 dict 值整体跳过（不炸编译）"""
        config = {
            "phase2_enabled": True,
            "phase2_debate_rounds": 3,
            "stage_overrides": {
                "research_debate": {"rounds": None},
                "bad_stage": "not-a-dict",
            },
        }
        params = params_from_legacy_config(config, ["market-analyst"])
        assert params.stage_overrides["research_debate"].rounds == 3
        assert "bad_stage" not in params.stage_overrides


class TestCompileRejections:
    def test_non_optional_stage_cannot_disable(self, spec):
        params = CompileParams(stage_overrides={"summary": StageOverride(enabled=False)})
        with pytest.raises(CompileError, match="非 optional"):
            compile_workflow(spec, params)

    def test_unknown_report_view(self, spec):
        drifted = spec.model_copy(
            update={
                "stages": tuple(
                    s.model_copy(update={"report_view": "ghost"}) if s.id == "research_debate" else s
                    for s in spec.stages
                )
            }
        )
        params = params_from_legacy_config({"phase2_enabled": True}, ["market-analyst"])
        with pytest.raises(CompileError, match="未知辩论报告视图"):
            compile_workflow(drifted, params)

    def test_unknown_node_ref(self, spec):
        drifted = spec.model_copy(
            update={
                "stages": tuple(s.model_copy(update={"node": "ghost"}) if s.id == "trader" else s for s in spec.stages)
            }
        )
        with pytest.raises(CompileError, match="不在 workflow nodes 库"):
            compile_workflow(drifted, CompileParams())

    def test_explicit_batch_subset_empty(self, spec):
        """显式 nodes 枚举的批阶段被裁空 → 拒绝（pool 批阶段不适用：装配层报错）"""
        from app.engine.orchestrator.workflow.spec import NodeRef

        stages = []
        for s in spec.stages:
            if s.id == "analysts":
                s = s.model_copy(update={"pool": None, "nodes": (NodeRef(ref="market-analyst"),)})
            stages.append(s)
        drifted = spec.model_copy(update={"stages": tuple(stages)})
        # 选了不在枚举里的 slug → 子集化后空
        params = params_from_legacy_config({}, ["news-analyst"])
        with pytest.raises(CompileError, match="子集化后为空"):
            compile_workflow(drifted, params)


class TestSnapshot:
    def test_snapshot_freezes_params(self, spec):
        params = params_from_legacy_config({"phase2_enabled": True, "phase2_debate_rounds": 2}, ["market-analyst"])
        plan = compile_workflow(spec, params, spec_hash="sha256:abc")
        snap = plan.snapshot()
        assert snap["workflow_slug"] == "default-4stage"
        assert snap["spec_hash"] == "sha256:abc"
        assert snap["params"]["stage_overrides"]["research_debate"]["rounds"] == 2
        assert snap["params"]["selected_nodes"] == ["market-analyst"]
        assert "compiled_at" in snap
