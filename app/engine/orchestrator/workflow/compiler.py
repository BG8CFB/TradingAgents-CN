"""Workflow 编译器：compile(spec, params) -> CompiledPlan（纯函数，无 I/O 无依赖注入）。

职责（设计文档 §4.4）：
- 把静态蓝图（WorkflowSpec）与运行时裁剪（CompileParams）合成为有序执行计划
- params_from_legacy_config 单点承接旧 API 契约（selected_analysts / phaseN_enabled /
  phaseN_debate_rounds / analyst_concurrency），analysis_service 构建零改动
- 编译期附加校验：非 optional 阶段不可关、rounds clamp [0,MAX_ROUNDS]、
  节点 ref 命中 nodes 库、辩论报告视图已注册

REPORT_VIEWS：辩论报告派生视图注册表（视图名 → (派生函数, has_latest_speaker)）。
P4 N 方辩论/新辩论族在此扩展（视图函数放 orchestrator/state.py）。
"""

from typing import Any, Callable, Dict, Optional, Sequence, Tuple

from .debate import BUILTIN_DEBATE_SIDE_KEYS
from .plan import CompiledPlan, MemoryReflection, PlannedBatch, PlannedDebate, PlannedNode, PlannedSingle
from .spec import (
    MAX_ROUNDS,
    CompileParams,
    DebateStage,
    NodeType,
    ParallelBatchStage,
    StageOverride,
    SingleStage,
    WorkflowSpec,
)
from ..state import (
    SIDE_ARGUMENT_TAGS,
    generic_report_content,
    investment_report_content,
    risk_report_content,
)

# 辩论报告派生视图注册表：视图名 → (rounds→reports 派生函数, latest_speaker 语义)
# risk 视图带 latest_speaker（旧 Phase3 语义：固定顺序中最后一个有产出的侧）；
# generic = P4-a 通用 N 方视图（无标签回退版占位，executor 按 sides 元数据
# 用 make_generic_report_content 物化带标签视图），latest_speaker 属旧 Phase3 契约
# 自定义组不维护
REPORT_VIEWS: Dict[str, Tuple[Callable[[Optional[Dict], str], str], bool]] = {
    "investment": (investment_report_content, False),
    "risk": (risk_report_content, True),
    "generic": (generic_report_content, False),
}


class CompileError(Exception):
    """编译失败（阶段/节点/参数不可满足；任务启动时抛出）"""


def params_from_legacy_config(config: Dict[str, Any], selected_analysts: Sequence[str]) -> CompileParams:
    """API 配置 → CompileParams（兼容映射唯一入口，P5-c 起新旧字段在此合流）。

    - phase2_enabled / phase3_enabled → research_debate / risk_debate 阶段启停
    - phase2_debate_rounds（回落 max_debate_rounds）/ phase3_debate_rounds（回落
      max_risk_discuss_rounds）→ 辩论附加轮数（clamp 在 compile 内）
    - analyst_concurrency → analysts 阶段并发覆盖
    - selected_analysts → parallel_batch 节点子集（保持提交序）
    - config["stage_overrides"]（P5-c 新字段，{stage_id: {enabled/rounds/concurrency}}）
      按字段级优先覆盖上述 legacy 映射；自定义工作流的任意 stage_id 直接直通
    """

    def _rounds(primary_key: str, fallback_key: str) -> int:
        v = config.get(primary_key)
        if v is None:
            v = config.get(fallback_key, 1)
        return int(v)

    overrides: Dict[str, StageOverride] = {
        "research_debate": StageOverride(
            enabled=bool(config.get("phase2_enabled", False)),
            rounds=_rounds("phase2_debate_rounds", "max_debate_rounds"),
        ),
        "risk_debate": StageOverride(
            enabled=bool(config.get("phase3_enabled", False)),
            rounds=_rounds("phase3_debate_rounds", "max_risk_discuss_rounds"),
        ),
    }
    concurrency = config.get("analyst_concurrency")
    if concurrency is not None:
        overrides["analysts"] = StageOverride(concurrency=max(1, int(concurrency)))

    # 显式 stage_overrides 字段级合并（None 值不覆盖 legacy 映射结果）
    explicit = config.get("stage_overrides") or {}
    if isinstance(explicit, dict):
        for stage_id, raw in explicit.items():
            if not isinstance(raw, dict):
                continue
            base = overrides[stage_id].model_dump() if stage_id in overrides else {}
            base.update({k: v for k, v in raw.items() if v is not None})
            overrides[stage_id] = StageOverride.model_validate(base)

    return CompileParams(
        selected_nodes=tuple(selected_analysts or ()),
        stage_overrides=overrides,
    )


def _planned_node(spec: WorkflowSpec, slug: str, *, stage_id: str) -> PlannedNode:
    """nodes 库 slug → 执行指令；critical = judge/trader/summarizer/terminal（失败重试 1 次）"""
    node = spec.node_by_slug(slug)
    if node is None:
        raise CompileError(f"阶段 {stage_id}: 节点 '{slug}' 不在 workflow nodes 库")
    return PlannedNode(
        slug=node.slug,
        kind=node.type,
        node_name=node.node_name,
        event_key=node.event_key,
        report_key=node.report_keys[0] if node.report_keys else "",
        memory=node.memory,
        critical=node.type not in (NodeType.ANALYST, NodeType.DEBATER),
        terminal=node.terminal,
    )


# 内置节点的反思 token 归属标识（旧 reflector 专用方法口径；自定义节点 = slug）
_REFLECTION_COMPONENT_KEYS: Dict[str, str] = {
    "bull-researcher": "BULL",
    "bear-researcher": "BEAR",
    "research-manager": "INVEST JUDGE",
    "trader": "TRADER",
    "risk-manager": "RISK JUDGE",
}


def _memory_reflections(stages: Tuple[Any, ...]) -> Tuple[MemoryReflection, ...]:
    """编译计划 → 记忆反思声明（P4-b：每个绑定记忆槽的节点一条）。

    纯函数遍历计划阶段：debater → 该侧累积发言史（label = 内置侧权威
    argument 标签 / 自定义侧 node_name）；judge → 所在辩论 state 的裁决；
    single → 主报告键。内置 5 槽的派生输入与旧 reflector 硬编码键逐字一致
    （等价证明见 tests/engine/workflow/test_p4b_terminal_contract.py）。
    """

    def _component_key(slug: str) -> str:
        return _REFLECTION_COMPONENT_KEYS.get(slug, slug)

    out = []
    for stage in stages:
        if isinstance(stage, PlannedDebate):
            for side in stage.sides:
                if not side.memory:
                    continue
                side_key = BUILTIN_DEBATE_SIDE_KEYS.get(side.slug, side.slug)
                out.append(
                    MemoryReflection(
                        slot=side.memory,
                        component_key=_component_key(side.slug),
                        kind="debater",
                        state_key=stage.state_key,
                        side_key=side_key,
                        label=SIDE_ARGUMENT_TAGS.get(side_key, side.node_name),
                    )
                )
            if stage.judge.memory:
                out.append(
                    MemoryReflection(
                        slot=stage.judge.memory,
                        component_key=_component_key(stage.judge.slug),
                        kind="judge",
                        state_key=stage.state_key,
                    )
                )
        elif isinstance(stage, PlannedSingle):
            node = stage.node
            if node.memory:
                out.append(
                    MemoryReflection(
                        slot=node.memory,
                        component_key=_component_key(node.slug),
                        kind="single",
                        report_key=node.report_key,
                    )
                )
    return tuple(out)


def compile_workflow(
    spec: WorkflowSpec,
    params: CompileParams,
    *,
    spec_hash: str = "",
) -> CompiledPlan:
    """编译：按 params 裁剪 spec 阶段/轮数/并发 → 有序执行计划（纯函数）。

    - 阶段启停：override.enabled 显式优先，缺省启用；关闭非 optional 阶段 = CompileError
    - pool 批阶段：selected_nodes 为子集（保持提交序；空集留给装配层报错，与现状一致）；
      显式 nodes 枚举的批阶段不受 selected_nodes 影响（P5 自定义工作流语义）
    - 未知 stage id 的 override 条目忽略（兼容映射针对默认工作流 stage id）
    """
    stages_out = []
    for stage in spec.stages:
        override = params.stage_overrides.get(stage.id)
        enabled = override.enabled if (override is not None and override.enabled is not None) else True
        if not enabled:
            if not stage.optional:
                raise CompileError(f"阶段 '{stage.id}' 非 optional，不可通过运行参数关闭")
            continue
        event_phase = stage.event_phase or stage.id

        if isinstance(stage, ParallelBatchStage):
            if stage.pool is not None:
                slugs = tuple(params.selected_nodes)
            else:
                slugs = tuple(ref.ref for ref in stage.nodes)
                if params.selected_nodes:
                    wanted = set(params.selected_nodes)
                    slugs = tuple(s for s in slugs if s in wanted)
                if not slugs:
                    raise CompileError(f"阶段 '{stage.id}': 节点子集化后为空")
            concurrency = stage.concurrency
            if override is not None and override.concurrency is not None:
                concurrency = max(1, int(override.concurrency))
            stages_out.append(
                PlannedBatch(
                    stage_id=stage.id,
                    event_phase=event_phase,
                    slugs=slugs,
                    concurrency=concurrency,
                )
            )
        elif isinstance(stage, DebateStage):
            if stage.report_view not in REPORT_VIEWS:
                raise CompileError(
                    f"阶段 '{stage.id}': 未知辩论报告视图 '{stage.report_view}'（已注册: {sorted(REPORT_VIEWS)}）"
                )
            rounds = stage.rounds
            if override is not None and override.rounds is not None:
                rounds = max(0, min(int(override.rounds), MAX_ROUNDS))
            stages_out.append(
                PlannedDebate(
                    stage_id=stage.id,
                    event_phase=event_phase,
                    state_key=stage.state_key,
                    sides=tuple(_planned_node(spec, s, stage_id=stage.id) for s in stage.sides),
                    judge=_planned_node(spec, stage.judge, stage_id=stage.id),
                    rounds=rounds,
                    report_view=stage.report_view,
                    inputs=tuple(stage.inputs.items()),
                )
            )
        elif isinstance(stage, SingleStage):
            stages_out.append(
                PlannedSingle(
                    stage_id=stage.id,
                    event_phase=event_phase,
                    node=_planned_node(spec, stage.node, stage_id=stage.id),
                    inputs=tuple(stage.inputs.items()),
                )
            )

    return CompiledPlan(
        workflow_slug=spec.slug,
        spec_version=spec.version,
        spec_hash=spec_hash,
        stages=tuple(stages_out),
        terminal=spec.terminal,
        params=params,
        memory_reflections=_memory_reflections(tuple(stages_out)),
    )
