"""输入渲染器（P3，设计文档 §4.6）：inputs 连线 → 黑板取值。

职责边界：
- 本模块只做「按连线声明取值」：报告槽（list 绑定 → {key: content}，缺键整段
  省略 = 现状动态收集语义）、field 槽（str 点路径 → 标量/嵌套值）、
  all_upstream 选择器（宽松模式全量报告）
- prompt 占位符（{{inputs.槽名}}）替换与缺槽降级文案（missing_policy）
- required_sources 编译期 fail-fast（裁掉必需分析师 → 拒绝任务，L263 行为变更）

纯函数（黑板 state 为 plain dict 入参）；显示名走 registry 单一权威表。
连线声明本身的合法性（可达性/槽覆盖）在 validator，不在此重复。
"""

import re
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

from .plan import CompiledPlan, PlannedBatch, PlannedDebate, PlannedSingle
from .spec import ALL_UPSTREAM, InputBinding, InputSlot, WorkflowSpec

# 占位符默认降级文案（missing_policy 未声明时）
DEFAULT_MISSING_TEXT = "暂无相关输入。"

_PLACEHOLDER = re.compile(r"\{\{inputs\.([A-Za-z0-9_\-\.]+)\}\}")


def _board(state: Dict[str, Any]) -> Dict[str, Any]:
    """黑板 reports 字典（形状异常时安全降级为空）"""
    reports = state.get("reports")
    return reports if isinstance(reports, dict) else {}


def resolve_reports(state: Dict[str, Any], keys: Iterable[str]) -> Dict[str, str]:
    """报告键（按连线枚举序）→ {key: content}。

    取值优先级：state["reports"] 黑板 → 顶层同名键（与 trader 现状一致）。
    缺键/空值整段省略——与现状「动态发现 + 黑名单排除」对缺项的行为等价。
    """
    board = _board(state)
    resolved: Dict[str, str] = {}
    for key in keys:
        value = board.get(key) or state.get(key)
        if value:
            resolved[key] = value
    return resolved


def all_upstream_reports(state: Dict[str, Any]) -> Dict[str, str]:
    """宽松模式选择器：黑板全部已有报告（内置工作流不使用，validator 拦截）"""
    board = _board(state)
    return {key: value for key, value in board.items() if value}


def resolve_field(state: Dict[str, Any], path: str) -> Any:
    """点路径 → 值（"a.b.c" 逐级下钻；顶层单段直接取；任一级缺失返回 None）"""
    value: Any = state
    for part in path.split("."):
        if not isinstance(value, dict):
            return None
        value = value.get(part)
        if value is None:
            return None
    return value


def resolve_inputs(
    stage_inputs: Dict[str, InputBinding],
    state: Dict[str, Any],
) -> Dict[str, Any]:
    """连线字典 → {slot: value}。

    str 绑定：含 "." = field 点路径；否则 = 单报告键（→ 报告内容，缺 = None）。
    list 绑定：报告键集合 → {key: content}。
    all_upstream：黑板全量报告（自定义工作流宽松模式）。
    """
    resolved: Dict[str, Any] = {}
    for slot, binding in stage_inputs.items():
        if binding == ALL_UPSTREAM:
            resolved[slot] = all_upstream_reports(state)
        elif isinstance(binding, str):
            if "." in binding:
                resolved[slot] = resolve_field(state, binding)
            else:
                resolved[slot] = resolve_reports(state, [binding]).get(binding)
        else:
            resolved[slot] = resolve_reports(state, binding)
    return resolved


def missing_value(slot: Optional[InputSlot]) -> str:
    """缺槽降级文案：契约 missing_policy 优先，否则默认占位"""
    if slot is not None and slot.missing_policy:
        return slot.missing_policy
    return DEFAULT_MISSING_TEXT


def format_report_bundle(reports: Dict[str, str]) -> str:
    """报告集合 → prompt 段落（显示名走 registry 单一权威表；<report> 边界防注入）"""
    from app.engine.orchestrator import registry

    parts: List[str] = []
    for key, content in reports.items():
        title = registry.report_title(key)
        parts.append(f"\n### {title}\n<report>\n{content}\n</report>\n")
    return "".join(parts)


def render_template(
    text: str,
    resolved: Dict[str, Any],
    slots: Optional[Dict[str, InputSlot]] = None,
) -> str:
    """{{inputs.槽名}} 占位符替换。

    - 槽值缺失（None）→ required 契约由编译期 fail-fast 把关，此处按
      missing_policy/默认占位降级（required 槽理论上到不了这里）
    - 报告集合值 → format_report_bundle 段落；其余 → str()
    - 未连线的未知槽名 → 保留原文（占位符笔误由库保存时的「占位符↔契约一一匹配」
      校验暴露，渲染器不做静默吞并）
    """
    slots = slots or {}

    def _sub(match: "re.Match[str]") -> str:
        name = match.group(1)
        if name not in resolved:
            return match.group(0)
        value = resolved[name]
        if value is None:
            return missing_value(slots.get(name))
        if isinstance(value, dict):
            return format_report_bundle(value)
        return str(value)

    return _PLACEHOLDER.sub(_sub, text)


def extract_placeholders(text: str) -> Tuple[str, ...]:
    """prompt 模板引用的全部槽名（库保存时与 template_inputs 契约一一匹配校验用）"""
    return tuple(_PLACEHOLDER.findall(text))


def _stage_participants(stage: Any) -> Tuple[str, ...]:
    """编译计划单阶段 → 参与 slug（批=成员；辩论=侧+judge；单=节点）"""
    if isinstance(stage, PlannedBatch):
        return tuple(stage.slugs)
    if isinstance(stage, PlannedDebate):
        return tuple(s.slug for s in stage.sides) + (stage.judge.slug,)
    if isinstance(stage, PlannedSingle):
        return (stage.node.slug,)
    return ()


def check_required_sources(
    plan: CompiledPlan,
    spec: WorkflowSpec,
    agent_contracts: Dict[str, List[dict]],
    analyst_report_keys: Dict[str, Tuple[str, ...]],
) -> List[str]:
    """编译期 required fail-fast：契约 required_sources 的键必须由计划内上游产出。

    判定顺序：阶段序累积产出集，节点只可依赖此前阶段的产出（同阶段成员间
    不可互相满足——辩论组输入是阶段开始时的快照）。返回错误列表（空 = 通过）；
    agent_contracts / analyst_report_keys 由调用方从 agent_specs 库与 registry 组装。
    """
    errors: List[str] = []
    produced: Set[str] = set()
    for stage in plan.stages:
        participants = _stage_participants(stage)
        # 先校验后累积：本阶段产出对同阶段成员不可见
        for slug in participants:
            for entry in agent_contracts.get(slug) or []:
                for key in entry.get("required_sources", ()):
                    if key not in produced:
                        errors.append(
                            f"节点 '{slug}' 的必需输入 '{key}' 未由计划内上游产出（检查是否裁掉了必需的分析师）"
                        )
        for slug in participants:
            if isinstance(stage, PlannedBatch):
                produced.update(analyst_report_keys.get(slug, ()))
            else:
                node = spec.node_by_slug(slug)
                if node is not None:
                    produced.update(node.report_keys)
    return errors
