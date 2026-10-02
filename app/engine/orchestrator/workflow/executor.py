"""Workflow 执行器：按 CompiledPlan 有序遍历阶段（编排与机制分离）。

等价性约束（golden 基线锁定，见 tests/engine/workflow/）：
- 本模块改的是「遍历什么」（plan 驱动），执行机制全部沿用 pipeline 模块级函数：
  顺序合并/辩论 barrier 合并/失败记录/report_ready diff 发射均 import 自 pipeline
- 闭包机制（_execute_node 重试/事件/计时、_run_debate_round 公平 barrier、
  _run_analyst 降级）与旧 run_pipeline 内实现逐行等价
- 内置 9 节点工厂绑定表（slug → 工厂）是 P2 内置工作流的 materialize 实现；
  P5 自定义节点类型在此扩展注册
"""

import asyncio
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

import logging

from .. import registry
from ..state import make_generic_report_content
from ..pipeline import (
    PipelineDeps,
    _emit_report_ready,
    _merge_debate_updates,
    _merge_state_update,
    _record_error,
    interpolate_percent,
)
from .compiler import REPORT_VIEWS
from .debate import BUILTIN_DEBATE_SIDE_KEYS, DebateGroup, DebateNodeBinding
from .plan import (
    MEMORY_SLOT_FIELDS,
    CompiledPlan,
    PlannedBatch,
    PlannedDebate,
    PlannedNode,
    PlannedSingle,
)

logger = logging.getLogger("orchestrator.pipeline")


def _materialize_node(slug: str, node: PlannedNode, deps: PipelineDeps):
    """PlannedNode → 节点执行函数（single 阶段内置节点工厂绑定表：trader/summary）。

    工厂 import 保持函数内延迟加载（与旧 run_pipeline 阶段块一致）。
    辩论组成员（辩手/judge）经 _materialize_side/_materialize_judge 物化
    （P4-a N 方泛化：带 DebateGroup 组拓扑上下文）；未注册 slug = 自定义
    spec 超出绑定范围，任务启动即失败。
    """

    def _trader():
        from app.engine.agents.stage_2.trader import create_trader

        return create_trader(deps.debate_client, _slot_memory(deps, node.memory))

    def _summary():
        from app.engine.agents.stage_4.summary_agent import create_summary_agent

        return create_summary_agent(deps.debate_client)

    factories: Dict[str, Callable[[], Any]] = {
        "trader": _trader,
        "summary": _summary,
    }
    factory = factories.get(slug)
    if factory is None:
        raise RuntimeError(f"节点 '{slug}'（{node.kind.value}）无内置工厂绑定（仅支持内置 single 节点）")
    return factory()


# 辩论侧 state 轮次键（slug → rounds[idx] 内的 side key）：
# 权威表在 debate.py（compiler 推导反思声明共用）；自定义辩手无条目 →
# side_key = slug 本身（无歧义，报告视图按 side_key 派生）
_DEBATE_SIDE_KEYS = BUILTIN_DEBATE_SIDE_KEYS

# 内置研究员/风险辩手的 side 参数（slug → 工厂 side 实参）
_BUILTIN_RESEARCHER_SIDES: Dict[str, str] = {
    "bull-researcher": "bull",
    "bear-researcher": "bear",
}
_BUILTIN_RISK_SIDES: Dict[str, str] = {
    "risky-analyst": "risky",
    "safe-analyst": "safe",
    "neutral-analyst": "neutral",
}

# 记忆槽位（NodeSpec.memory 值域）→ PipelineDeps 字段绑定表（§4.5 记忆绑定泛化）：
# 权威表在 plan.py（runtime 反思遍历共用）
_MEMORY_SLOT_FIELDS = MEMORY_SLOT_FIELDS


def _slot_memory(deps: PipelineDeps, slot: Optional[str]):
    """记忆槽位名 → deps 上的记忆实例（未知槽位/缺实例返回 None，不阻断）"""
    if not slot:
        return None
    return getattr(deps, _MEMORY_SLOT_FIELDS.get(slot, ""), None)


def _materialize_side(node: PlannedNode, deps: PipelineDeps, group, side_key: str):
    """辩论侧辩手物化：内置 5 辩手走各自工厂（带组拓扑），自定义 slug 走通用工厂"""
    if node.slug in _BUILTIN_RESEARCHER_SIDES:
        from app.engine.agents.stage_2.researcher_factory import create_researcher

        return create_researcher(
            deps.debate_client,
            _slot_memory(deps, node.memory),
            side=_BUILTIN_RESEARCHER_SIDES[node.slug],
            group=group,
        )
    if node.slug in _BUILTIN_RISK_SIDES:
        from app.engine.agents.stage_3.debator_factory import create_debator

        return create_debator(
            deps.debate_client,
            side=_BUILTIN_RISK_SIDES[node.slug],
            group=group,
        )
    from app.engine.agents.debaters import create_generic_debater

    binding = DebateNodeBinding(
        slug=node.slug,
        node_name=node.node_name,
        event_key=node.event_key,
        report_key=node.report_key,
        side_key=side_key,
        memory=node.memory or "",
        terminal=node.terminal,
    )
    return create_generic_debater(deps.debate_client, binding, group)


def _materialize_judge(node: PlannedNode, deps: PipelineDeps, group):
    """辩论 judge 物化：内置 2 judge 走各自工厂（读各自固定辩论 state），自定义走通用工厂。

    注意：内置 judge 工厂内部固定读取其原配辩论 state（research-manager →
    investment_debate_state 的 bull/bear 卷宗；risk-manager → risk_debate_state
    三方卷宗），把它们放进自定义 state_key/扩充 sides 的辩论组只会裁决内置
    双方/三方——自定义 N 方组应配自定义 judge（通用工厂按组拓扑注入全部侧）。
    """
    if node.slug == "research-manager":
        from app.engine.agents.stage_2.research_manager import create_research_manager

        return create_research_manager(deps.debate_client, deps.invest_judge_memory)
    if node.slug == "risk-manager":
        from app.engine.agents.stage_3.risk_manager import create_risk_manager

        return create_risk_manager(deps.debate_client, deps.risk_manager_memory)
    from app.engine.agents.debaters import create_generic_judge

    binding = DebateNodeBinding(
        slug=node.slug,
        node_name=node.node_name,
        event_key=node.event_key,
        report_key=node.report_key,
        memory=node.memory or "",
        terminal=node.terminal,
    )
    return create_generic_judge(deps.debate_client, binding, group, memory=_slot_memory(deps, node.memory))


async def run_compiled(
    plan: CompiledPlan,
    deps: PipelineDeps,
    state: Dict[str, Any],
    *,
    event_sink: Optional[Any],
    mcp_tools: List,
    node_timings: Dict[str, float],
    progress_range: tuple = (0, 100),
) -> None:
    """按 plan 有序执行全部阶段（就地更新 state；异常语义/partial_state 由调用方处理）。

    config 读取（max_tool_calls / enable_subagent / debate_parallel）是执行机制参数，
    不属于拓扑，保持经 deps.config 透传（现状行为）。
    """
    config = deps.config or {}
    debate_parallel = bool(config.get("debate_parallel", True))

    completed_box = [0]
    # 进度分母：编译期计划原子数先兜底（无 batch 阶段的工作流没有运行时回填点）；
    # batch 阶段按实际装配数覆盖
    total_units_box = [plan.total_units()]
    progress_lo, progress_hi = progress_range

    def _progress_text(node_name: str) -> str:
        """节点名 → 中文进度文案（registry；无映射回退节点名）"""
        try:
            return registry.progress_text(node_name) or f"🔍 {node_name}"
        except Exception as e:  # noqa: BLE001
            logger.warning(f"⚠️ [orchestrator] 进度文案解析失败: {e}")
            return f"🔍 {node_name}"

    async def _emit_unit_done(node_name: str, phase: str, agent_key: str) -> None:
        """单元完成（含失败降级）即计数 +1 并发射结构化进度事件（completed/total/percent/step_text）"""
        if event_sink is None:
            return
        completed_box[0] += 1
        total = total_units_box[0]
        percent = interpolate_percent(completed_box[0], total, progress_lo, progress_hi)
        try:
            await event_sink.emit(
                "progress",
                agent_key=agent_key or node_name,
                phase=phase,
                completed=completed_box[0],
                total=total,
                percent=percent,
                step_text=_progress_text(node_name),
            )
        except Exception as e:  # noqa: BLE001
            logger.warning(f"⚠️ [orchestrator] 进度事件发射失败: {e}")

    async def _execute_node(
        node_name: str,
        node_fn,
        st: Dict[str, Any],
        event_key: str = "",
        display_name: str = "",
        critical: bool = False,
        limit_key: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> Dict[str, Any]:
        """执行单个节点：计时 + 事件 + 失败记录/重试 + 模型级并发限流，返回 update（不合并 state）"""
        from app.llm.limiter import alimit

        key = event_key or registry.event_key_for_node(node_name)
        start = time.time()
        if event_sink is not None:
            event_sink.mark_running(key)
            await event_sink.emit(
                "agent_start",
                agent_key=key,
                phase=st.get("_phase", ""),
                name=display_name or registry.display_name_for_node(node_name) or node_name,
            )
        try:
            try:
                async with alimit(limit_key, limit):
                    update = await node_fn(st)
            except Exception as e:  # noqa: BLE001 - 节点异常：先记录再决定重试/上抛
                logger.error(f"❌ [orchestrator] 节点 {node_name} 异常: {e}", exc_info=True)
                if not critical:
                    _record_error(st, node_name, str(e), start, retried=False)
                    update = {}
                else:
                    logger.warning(f"🔁 [orchestrator] 关键节点 {node_name} 失败，重试 1 次")
                    try:
                        async with alimit(limit_key, limit):
                            update = await node_fn(st)
                    except Exception as e2:  # 重试仍失败 → 记录后上抛（不再静默吞掉）
                        _record_error(st, node_name, str(e2), start, retried=True)
                        raise
        finally:
            elapsed = time.time() - start
            node_timings[node_name] = elapsed
            logger.info(f"⏱️ [{node_name}] 耗时: {elapsed:.2f}秒")
            if event_sink is not None:
                event_sink.mark_completed(key)
                await event_sink.emit("agent_end", agent_key=key, duration_ms=int(elapsed * 1000))
                # 完成驱动计数（critical 重试上抛路径同样经过 finally → 计数，不卡死）
                await _emit_unit_done(node_name, phase=st.get("_phase", ""), agent_key=key)
        return update or {}

    async def _run_node(
        node_name: str,
        node_fn,
        st: Dict[str, Any],
        event_key: str = "",
        display_name: str = "",
        critical: bool = False,
        limit_key: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> None:
        """_execute_node + 顺序合并（串行路径：Trader/Judge/Manager/Summary 等）"""
        key = event_key or registry.event_key_for_node(node_name)
        update = await _execute_node(
            node_name,
            node_fn,
            st,
            event_key=event_key,
            display_name=display_name,
            critical=critical,
            limit_key=limit_key,
            limit=limit,
        )
        _before_reports = dict(st.get("reports") or {})  # 合并前快照（report_ready diff 依据）
        _merge_state_update(st, update or {})
        # 单份报告就绪即发（diff 本次 update 的 reports：新增或内容变化的 key）
        await _emit_report_ready(
            event_sink,
            update or {},
            agent_key=key,
            phase=st.get("_phase", ""),
            before_reports=_before_reports,
            display_name=display_name or registry.display_name_for_node(node_name) or "",
        )

    async def _run_debate_round(
        side_nodes: List[Tuple[str, str, Any]],
        st: Dict[str, Any],
        *,
        state_key: str,
        side_keys: List[str],
        report_keys: List[str],
        report_view: Callable[[Dict[str, Any], str], str],
        has_latest_speaker: bool = False,
    ) -> None:
        """同轮多方并行辩论（barrier 语义）：gather 并行执行各侧 → 全部完成后字段级合并。

        side_nodes = (node_name, event_key, 节点函数)：event_key 来自编译期
        NodeSpec（内置值与 registry 查表一致；自定义节点 registry 无条目，必须
        显式传递，否则事件流 agent_key 会回退显示名）。
        公平性保证：各侧节点只读 rounds[0:current_round_index]（完整历史轮，
        不见本轮对手），与旧串行的上下文注入逐字节一致；差异仅在执行顺序。
        """
        updates = await asyncio.gather(
            *[
                _execute_node(
                    node_name,
                    node_fn,
                    st,
                    event_key=event_key,
                    critical=False,
                    limit_key=deps.debate_limit_key,
                    limit=deps.debate_limit,
                )
                for node_name, event_key, node_fn in side_nodes
            ]
        )

        _before_reports = dict(st.get("reports") or {})
        _merge_debate_updates(
            st,
            updates,
            state_key=state_key,
            side_keys=side_keys,
            has_latest_speaker=has_latest_speaker,
        )

        # reports 统一重派生（各 update 内的派生视图只含自己本轮，不可信）+ report_ready 事件
        ds = st.get(state_key) or {}
        for (node_name, event_key, _fn), side_key, report_key in zip(side_nodes, side_keys, report_keys):
            content = report_view(ds, side_key)
            if not content:
                continue
            st.setdefault("reports", {})[report_key] = content
            await _emit_report_ready(
                event_sink,
                {"reports": {report_key: content}},
                agent_key=event_key or registry.event_key_for_node(node_name),
                phase=st.get("_phase", ""),
                before_reports=_before_reports,
                display_name=registry.display_name_for_node(node_name) or node_name,
            )

    async def _run_batch_stage(stage: PlannedBatch) -> None:
        """并行批阶段（分析师段）：装配 specs → 并发执行 → 按 specs 序回填合并"""
        from ..agents import build_analyst_specs, run_analyst

        specs = await build_analyst_specs(
            list(stage.slugs),
            deps.toolkit,
            max_tool_calls=int(config.get("max_tool_calls", 12)),
            mcp_tools=mcp_tools,
            enable_subagent=bool(config.get("enable_subagent", False)),
        )
        concurrency = max(1, int(stage.concurrency or 1))
        # 模型级并发限额（LLMConfig.max_concurrency）封顶编排并行度：灵活占位语义
        if deps.analyst_limit:
            concurrency = min(concurrency, int(deps.analyst_limit))
        semaphore = asyncio.Semaphore(concurrency)
        # 进度分母在此确定（分析师实际装配数 + 各阶段展开节点数）
        total_units_box[0] = plan.total_units(len(specs))

        async def _run_analyst(internal_key: str, spec) -> Dict[str, Any]:
            """单个分析师并行单元：事件/计时/进度 + run_analyst（失败降级）"""
            node_name = registry.format_analyst_node(internal_key)
            start = time.time()
            if event_sink is not None:
                event_sink.mark_running(internal_key)
                await event_sink.emit(
                    "agent_start",
                    agent_key=internal_key,
                    phase=stage.event_phase,
                    name=spec.name,
                )
            try:
                from app.llm.limiter import alimit

                async with semaphore, alimit(deps.analyst_limit_key, deps.analyst_limit):
                    return await run_analyst(spec, deps.analyst_client, state, event_sink=event_sink)
            except Exception as e:  # noqa: BLE001 - run_analyst 内部已有降级，此处兜底
                logger.error(f"❌ [orchestrator] 分析师 {spec.name} 异常: {e}", exc_info=True)
                _record_error(state, node_name, str(e), start, retried=False)
                return {}
            finally:
                elapsed = time.time() - start
                node_timings[node_name] = elapsed
                logger.info(f"⏱️ [{node_name}] 耗时: {elapsed:.2f}秒")
                if event_sink is not None:
                    event_sink.mark_completed(internal_key)
                    await event_sink.emit(
                        "agent_end",
                        agent_key=internal_key,
                        duration_ms=int(elapsed * 1000),
                    )
                    await _emit_unit_done(node_name, stage.event_phase, internal_key)

        analyst_results = await asyncio.gather(*[_run_analyst(k, s) for k, s in specs.items()])
        # 按 specs 序回填合并（与旧串行执行的 state 报告顺序一致）
        for (_internal_key, _spec), update in zip(specs.items(), analyst_results):
            _before = dict(state.get("reports") or {})
            _merge_state_update(state, update or {})
            await _emit_report_ready(
                event_sink,
                update or {},
                agent_key=_internal_key,
                phase=stage.event_phase,
                before_reports=_before,
            )

    async def _run_debate_stage(stage: PlannedDebate) -> None:
        """辩论阶段：轮次公平发言（parallel/serial 双路径）+ judge 裁决（N 方泛化）"""
        # 与实际循环次数同步（state 初始值为硬编码默认，用于日志分母与 prompt 文案）；
        # setdefault 兼容自定义辩论组的 state_key（create_initial_state 只建两个内置键）
        state.setdefault(stage.state_key, {})["max_rounds"] = stage.rounds + 1

        side_keys = [_DEBATE_SIDE_KEYS.get(n.slug, n.slug) for n in stage.sides]
        node_names = [n.node_name for n in stage.sides]
        # 报告派生视图绑定：generic = 按 sides 元数据物化带标签视图；
        # 内置 investment/risk 视图直接取注册表（行为与旧路径一致）
        if stage.report_view == "generic":
            view_fn = make_generic_report_content(dict(zip(side_keys, node_names)))
            has_latest_speaker = False
        else:
            view_fn, has_latest_speaker = REPORT_VIEWS[stage.report_view]
        group = DebateGroup(
            state_key=stage.state_key,
            per_turn=len(side_keys),
            sides=tuple(zip(side_keys, node_names)),
            report_view=view_fn,
            event_phase=stage.event_phase,
            judge_decision_field=plan.terminal.decision_field if stage.judge.terminal else "",
        )

        side_nodes: List[Tuple[str, str, Any]] = [
            (n.node_name, n.event_key, _materialize_side(n, deps, group, sk)) for n, sk in zip(stage.sides, side_keys)
        ]
        report_keys = [n.report_key for n in stage.sides]

        # 总发言 len(sides)*(rounds+1)。debate_parallel=True：同轮各方并行 + barrier
        # （上下文注入只读完整历史轮，与串行等价）；False：旧串行交替（回退保险丝）
        for _round in range(stage.rounds + 1):
            if debate_parallel:
                await _run_debate_round(
                    side_nodes,
                    state,
                    state_key=stage.state_key,
                    side_keys=side_keys,
                    report_keys=report_keys,
                    report_view=view_fn,
                    has_latest_speaker=has_latest_speaker,
                )
            else:
                for node_name, event_key, node_fn in side_nodes:
                    await _run_node(
                        node_name,
                        node_fn,
                        state,
                        event_key=event_key,
                        limit_key=deps.debate_limit_key,
                        limit=deps.debate_limit,
                    )
        await _run_node(
            stage.judge.node_name,
            _materialize_judge(stage.judge, deps, group),
            state,
            event_key=stage.judge.event_key,
            critical=True,
            limit_key=deps.debate_limit_key,
            limit=deps.debate_limit,
        )

    async def _run_single_stage(stage: PlannedSingle) -> None:
        """单节点阶段（trader / summary；critical 节点重试后仍失败则上抛）"""
        await _run_node(
            stage.node.node_name,
            _materialize_node(stage.node.slug, stage.node, deps),
            state,
            critical=True,
            limit_key=deps.debate_limit_key,
            limit=deps.debate_limit,
        )

    for stage in plan.stages:
        state["_phase"] = stage.event_phase
        if isinstance(stage, (PlannedDebate, PlannedSingle)):
            # 输入声明化取值（P3 §4.6）：阶段开始时按 inputs 连线从黑板快照，
            # 节点消费集 = 声明集（黑名单动态收集退役）；辩论组各侧/judge 共用
            # 同一份快照（同轮防泄漏由 debate 机制保证，输入在阶段内不随轮次变化）
            from .inputs import resolve_inputs

            state["_stage_inputs"] = resolve_inputs(dict(stage.inputs), state)
        if isinstance(stage, PlannedBatch):
            await _run_batch_stage(stage)
        elif isinstance(stage, PlannedDebate):
            await _run_debate_stage(stage)
        else:
            await _run_single_stage(stage)
