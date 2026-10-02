"""WorkflowSpec 校验器（P2 结构 + P3 输入连线；错误定位到字段路径）。

三类规则：
- 结构校验：stage id 唯一 / ref 命中 nodes 库或 phase1 / debate sides≥2 有 judge /
  report_key 唯一 / execution 与 type 的匹配约束 / parallel_batch 池与枚举二选一 /
  terminal 写入者存在且类型兼容
- 输入连线校验（P3）：inputs 连线键必须由拓扑序在前的阶段产出（报告键 /
  field 点路径 / all_upstream 选择器）；all_upstream 宽松模式仅自定义工作流可用
- 锚点校验（防两处漂移）：内置种子的 9 个非分析师节点标识 ↔ P1 registry 静态段
  逐项一致（slug/node_name/event_key/report_keys/kind）——违反即启动失败

槽覆盖校验（连线覆盖 template_inputs 引用的全部槽）需要库层契约（agent_specs），
独立入口 validate_inputs_coverage，由保存/编译入口随 agent_contracts 调用。

返回 list[str] 错误（空 = 通过）；validate_or_raise 聚合抛 WorkflowValidationError。
锚点校验需要读 registry（YAML I/O），独立入口 validate_registry_anchor。
"""

from typing import Dict, List, Set, Tuple

from .spec import (
    ALL_UPSTREAM,
    DebateStage,
    NodeType,
    ParallelBatchStage,
    SingleStage,
    WorkflowSpec,
    normalize_binding,
)


class WorkflowValidationError(Exception):
    """校验失败（errors 为全部错误信息，含字段路径）"""

    def __init__(self, errors: List[str]):
        self.errors = errors
        super().__init__("; ".join(errors) if errors else "workflow validation failed")


def _phase1_slugs() -> set:
    """phase1 分析师 slug 全集（registry 动态段）"""
    from app.engine.orchestrator import registry

    return {i.slug for i in registry._load_identities() if i.is_analyst}


def _phase1_report_keys() -> Set[str]:
    """phase1 分析师报告键全集（pool 阶段的产出集；registry 动态段）"""
    from app.engine.orchestrator import registry

    keys: Set[str] = set()
    for identity in registry._load_identities():
        if identity.is_analyst:
            keys.update(identity.report_keys)
    return keys


def stage_output_keys(spec: WorkflowSpec, stage) -> Tuple[Set[str], Set[str]]:
    """单个 stage 的产出集 → (报告键集, field 根集)。

    报告键 = 各成员节点 report_keys 并集（reports 黑板主输出）；
    field 根 = debate 的 state_key（judge_decision/rounds 等附带字段的点路径前缀）
    + terminal 节点写入的 decision_field（顶层 field）。
    """
    report_keys: Set[str] = set()
    field_roots: Set[str] = set()
    if isinstance(stage, ParallelBatchStage):
        if stage.pool is not None:
            report_keys |= _phase1_report_keys()
        for ref in stage.nodes:
            node = spec.node_by_slug(ref.ref)
            if node is not None:
                report_keys.update(node.report_keys)
            else:
                # phase1 分析师 ref：经 registry 动态段取报告键
                from app.engine.orchestrator import registry

                for identity in registry._load_identities():
                    if identity.slug == ref.ref:
                        report_keys.update(identity.report_keys)
    elif isinstance(stage, DebateStage):
        field_roots.add(stage.state_key)
        for slug in (*stage.sides, stage.judge):
            node = spec.node_by_slug(slug)
            if node is not None:
                report_keys.update(node.report_keys)
                if node.terminal:
                    field_roots.add(spec.terminal.decision_field)
    elif isinstance(stage, SingleStage):
        node = spec.node_by_slug(stage.node)
        if node is not None:
            report_keys.update(node.report_keys)
            if node.terminal:
                field_roots.add(spec.terminal.decision_field)
    return report_keys, field_roots


def _check_binding(
    binding: Tuple[str, ...],
    produced_reports: Set[str],
    produced_fields: Set[str],
) -> List[str]:
    """连线键元组 → 不可达错误列表（报告键直接命中；点路径按根前缀命中）"""
    problems = []
    for key in binding:
        if key == ALL_UPSTREAM:
            continue  # 选择器合法性在调用方按 builtin 判定
        if key in produced_reports:
            continue
        root = key.split(".", 1)[0]
        if key in produced_fields or root in produced_fields:
            continue
        problems.append(f"'{key}' 未由任何上游阶段产出")
    return problems


def validate_inputs(spec: WorkflowSpec) -> List[str]:
    """输入连线校验：连线键可达性 + all_upstream 使用限制（纯 spec 层，无库契约）。

    可达性按「拓扑序在前的全部阶段产出并集」判定；optional 阶段的产出同样合法
    （运行期被关闭时由 missing_policy 降级，非结构错误）。
    """
    errors: List[str] = []
    produced_reports: Set[str] = set()
    produced_fields: Set[str] = set()

    def _check_owner(path: str, inputs: Dict[str, object]) -> None:
        for slot, binding in inputs.items():
            if not isinstance(binding, (str, list)):
                errors.append(f"{path}.inputs.{slot}: 连线值必须是 str 或 list（当前 {type(binding).__name__}）")
                continue
            keys = normalize_binding(binding)
            if ALL_UPSTREAM in keys:
                if spec.builtin:
                    errors.append(f"{path}.inputs.{slot}: 内置工作流禁用 all_upstream（须逐槽显式枚举）")
                continue
            for problem in _check_binding(keys, produced_reports, produced_fields):
                errors.append(f"{path}.inputs.{slot}: {problem}")

    for idx, stage in enumerate(spec.stages):
        path = f"stages[{idx}] ({stage.id})"
        if isinstance(stage, ParallelBatchStage):
            for ref_idx, ref in enumerate(stage.nodes):
                _check_owner(f"{path}.nodes[{ref_idx}] ({ref.ref})", ref.inputs)
        elif isinstance(stage, DebateStage):
            _check_owner(f"{path}", stage.inputs)
        elif isinstance(stage, SingleStage):
            _check_owner(f"{path}", stage.inputs)
        # 本 stage 产出在遍历后累积（下游才可引用）
        stage_reports, stage_fields = stage_output_keys(spec, stage)
        produced_reports |= stage_reports
        produced_fields |= stage_fields

    return errors


def validate_inputs_coverage(
    spec: WorkflowSpec,
    agent_contracts: Dict[str, List[dict]],
) -> List[str]:
    """槽覆盖校验：库契约 template_inputs 引用的每个槽都被工作流连线覆盖。

    agent_contracts: slug → template_inputs 条目列表（agent_specs 库读取方组装）。
    覆盖层级：debate 成员（sides+judge）看组输入；single 看 stage inputs；
    parallel_batch 成员看 NodeRef.inputs。无契约的节点跳过。
    """
    errors: List[str] = []

    def _covered(slots: List[str], wired: Set[str], path: str, slug: str) -> None:
        for slot in slots:
            if slot not in wired:
                errors.append(f"{path}: 节点 '{slug}' 的输入槽 '{slot}' 未连线（template_inputs 契约要求覆盖）")

    for idx, stage in enumerate(spec.stages):
        path = f"stages[{idx}] ({stage.id})"
        if isinstance(stage, ParallelBatchStage):
            for ref in stage.nodes:
                contract = agent_contracts.get(ref.ref) or []
                _covered([c["slot"] for c in contract], set(ref.inputs), f"{path}.nodes ({ref.ref})", ref.ref)
        elif isinstance(stage, DebateStage):
            group_slots = set(stage.inputs)
            for slug in (*stage.sides, stage.judge):
                contract = agent_contracts.get(slug) or []
                _covered([c["slot"] for c in contract], group_slots, path, slug)
        elif isinstance(stage, SingleStage):
            contract = agent_contracts.get(stage.node) or []
            _covered(
                [c["slot"] for c in contract],
                set(stage.inputs),
                path,
                stage.node,
            )
    return errors


def validate(spec: WorkflowSpec) -> List[str]:
    """结构校验（纯函数，无 I/O）；返回错误列表，空 = 通过"""
    errors: List[str] = []

    # ── stage id 唯一 ──
    stage_ids = [s.id for s in spec.stages]
    dup_ids = {sid for sid in stage_ids if stage_ids.count(sid) > 1}
    if dup_ids:
        errors.append(f"stages: id 重复 {sorted(dup_ids)}")

    node_slugs = {n.slug for n in spec.nodes}

    # ── nodes 库内 slug 唯一 / report_key 唯一 / type-execution 匹配 ──
    if len(node_slugs) != len(spec.nodes):
        errors.append("nodes: slug 重复")
    seen_report_keys: dict = {}
    for idx, node in enumerate(spec.nodes):
        if node.type == NodeType.DEBATER and node.execution.value != "single_turn":
            errors.append(f"nodes[{idx}] ({node.slug}): debater 强制 single_turn（辩论公平性约束）")
        if node.type == NodeType.ANALYST and node.execution.value != "tool_loop":
            errors.append(f"nodes[{idx}] ({node.slug}): analyst 强制 tool_loop")
        for rk in node.report_keys:
            if rk in seen_report_keys:
                errors.append(f"nodes[{idx}] ({node.slug}): report_key '{rk}' 与节点 '{seen_report_keys[rk]}' 重复")
            else:
                seen_report_keys[rk] = node.slug

    # ── phase1 引用合法性（池阶段节点 + stage ref）──
    phase1 = _phase1_slugs()
    for idx, stage in enumerate(spec.stages):
        path = f"stages[{idx}] ({stage.id})"
        if isinstance(stage, ParallelBatchStage):
            if bool(stage.nodes) == (stage.pool is not None):
                errors.append(f"{path}: nodes 与 pool 必须二选一")
            for ref_idx, ref in enumerate(stage.nodes):
                if ref.ref not in node_slugs and ref.ref not in phase1:
                    errors.append(f"{path}.nodes[{ref_idx}]: ref '{ref.ref}' 未命中 nodes 库或 phase1")
        elif isinstance(stage, DebateStage):
            if len(stage.sides) < 2:
                errors.append(f"{path}.sides: 辩论组至少 2 方（当前 {len(stage.sides)}）")
            for side_idx, side in enumerate(stage.sides):
                if side not in node_slugs:
                    errors.append(f"{path}.sides[{side_idx}]: '{side}' 未命中 nodes 库（辩手不可来自 phase1 池）")
            if not stage.judge:
                errors.append(f"{path}.judge: 辩论组必须有 judge")
            elif stage.judge not in node_slugs:
                errors.append(f"{path}.judge: '{stage.judge}' 未命中 nodes 库")
            else:
                judge_node = spec.node_by_slug(stage.judge)
                if judge_node and judge_node.type not in (NodeType.JUDGE, NodeType.TERMINAL):
                    errors.append(f"{path}.judge: '{stage.judge}' type={judge_node.type.value} 不是 judge/terminal")
        elif isinstance(stage, SingleStage):
            if stage.node not in node_slugs:
                errors.append(f"{path}.node: '{stage.node}' 未命中 nodes 库")

    # ── 辩手不能同时是 judge ──
    for idx, stage in enumerate(spec.stages):
        if isinstance(stage, DebateStage) and stage.judge in stage.sides:
            errors.append(f"stages[{idx}] ({stage.id}): judge '{stage.judge}' 不能同时是辩手")

    # ── terminal 契约 ──
    if not spec.terminal.decision_field:
        errors.append("terminal.decision_field: 必填")
    terminal_nodes = [n for n in spec.nodes if n.terminal]
    if not terminal_nodes:
        errors.append("terminal: 工作流内无 terminal: true 节点（decision_field 无写入者）")
    else:
        for node in terminal_nodes:
            if node.type not in (NodeType.JUDGE, NodeType.TERMINAL):
                errors.append(
                    f"nodes ('{node.slug}'): terminal 标记只允许 judge/terminal 类型（当前 {node.type.value}）"
                )
    if not spec.terminal.summary_node:
        errors.append("terminal.summary_node: 必填")
    elif spec.node_by_slug(spec.terminal.summary_node) is None:
        errors.append(f"terminal.summary_node: '{spec.terminal.summary_node}' 未命中 nodes 库")

    # ── 输入连线（P3）──
    errors.extend(validate_inputs(spec))

    return errors


def validate_registry_anchor(spec: WorkflowSpec) -> List[str]:
    """锚点校验：内置非分析师节点标识 ↔ registry 静态段逐项一致。

    P2 防两处漂移的运行时防线（种子誊抄错误在启动/编译时暴露而非 golden 对比时）。
    返回错误列表，空 = 通过。
    """
    from app.engine.orchestrator import registry

    errors: List[str] = []
    static_identities = [i for i in registry._load_identities() if not i.is_analyst]
    by_slug = {i.slug: i for i in static_identities}

    seed_builtins = [n for n in spec.nodes if n.builtin]
    seed_slugs = {n.slug for n in seed_builtins}
    reg_slugs = set(by_slug)
    only_seed = sorted(seed_slugs - reg_slugs)
    only_reg = sorted(reg_slugs - seed_slugs)
    if only_seed:
        errors.append(f"nodes: 种子节点 {only_seed} 不存在于 registry 静态段")
    if only_reg:
        errors.append(f"nodes: registry 静态段节点 {only_reg} 缺失于种子")

    for node in seed_builtins:
        identity = by_slug.get(node.slug)
        if identity is None:
            continue
        if node.node_name != identity.node_name:
            errors.append(f"nodes ({node.slug}): node_name '{node.node_name}' ≠ registry '{identity.node_name}'")
        if node.event_key != identity.event_key:
            errors.append(f"nodes ({node.slug}): event_key '{node.event_key}' ≠ registry '{identity.event_key}'")
        if tuple(node.report_keys) != tuple(identity.report_keys):
            errors.append(
                f"nodes ({node.slug}): report_keys {list(node.report_keys)} ≠ registry {list(identity.report_keys)}"
            )
        if node.type.value != identity.kind:
            errors.append(f"nodes ({node.slug}): type '{node.type.value}' ≠ registry kind '{identity.kind}'")
    return errors


def validate_or_raise(spec: WorkflowSpec, *, check_anchor: bool = True) -> None:
    """全量校验（结构 + 锚点），失败抛 WorkflowValidationError（聚合全部错误）。

    锚点校验仅对内置工作流（spec.builtin=True）执行：锚点防的是「内置种子 ↔
    registry 静态段」两处誊抄漂移；自定义工作流的 nodes 库引用内置节点子集
    + 自定义节点，不要求 registry 全集，逐节点一致性由引用本身的 ref 命中
    校验保证。
    """
    errors = validate(spec)
    if check_anchor and spec.builtin:
        errors.extend(validate_registry_anchor(spec))
    if errors:
        raise WorkflowValidationError(errors)
