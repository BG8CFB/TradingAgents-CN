"""
保序流水线（替代 LangGraph graph/setup.py 的编排）

硬约束（与旧图语义完全一致，禁止漂移）：
- Phase 1 分析师严格串行（单点封装 run_stage，预留后期并行）
- Phase 2 公平辩论：Bull 先发言，之后 Bull/Bear 交替，各发言 rounds+1 次，
  总发言上限 2*(rounds+1)（节点内 count/current_round_index=count//2 语义保留）
- Trader 恒执行（phase2 关闭时直接从分析师进入）
- Phase 3 风险循环固定 Risky→Safe→Neutral，总发言上限 3*(rounds+1)
- Summary 恒执行
- phase2/phase3 开关三拓扑：P2+P3 / P2 / 仅 P3(P2 关→分析师直连 Trader)
"""

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

import logging

from .state import create_initial_state, export_legacy_state

# 节点名 → 配置 slug 映射：事件 payload.name 用 YAML 中的中文名（agent_key 仍为英文节点名，
# 保证历史事件兼容与用户消息门禁稳定）。Summary Agent 无 slug 配置，用固定中文名。
_NODE_SLUG_MAP: Dict[str, str] = {
    "Bull Researcher": "bull-researcher",
    "Bear Researcher": "bear-researcher",
    "Research Manager": "research-manager",
    "Trader": "trader",
    "Risky Analyst": "risky-analyst",
    "Safe Analyst": "safe-analyst",
    "Neutral Analyst": "neutral-analyst",
    "Risk Judge": "risk-manager",
}
_NODE_DISPLAY_FALLBACK: Dict[str, str] = {
    "Summary Agent": "报告总结",
}
# 节点名 → 事件流 agent_key 映射：与各节点内部 run_conversation 的 agent_key 对齐
# （researcher_factory/debator_factory/trader/summary 等），否则同一智能体会在面板分裂成
# 两个 tab（生命周期事件一个键、LLM 事件另一个键）。agent_key 保持英文稳定标识。
_NODE_EVENT_KEYS: Dict[str, str] = {
    "Bull Researcher": "researcher_bull",
    "Bear Researcher": "researcher_bear",
    "Research Manager": "research_manager",
    "Trader": "trader",
    "Risky Analyst": "risk_debator_risky",
    "Safe Analyst": "risk_debator_safe",
    "Neutral Analyst": "risk_debator_neutral",
    "Risk Judge": "risk_manager",
    "Summary Agent": "summary",
}
# 模块级缓存：配置文件在运行期不变化，进程内解析一次即可
_NODE_DISPLAY_NAMES: Optional[Dict[str, str]] = None


def _resolve_display_names() -> Dict[str, str]:
    global _NODE_DISPLAY_NAMES
    if _NODE_DISPLAY_NAMES is None:
        from app.engine.agents.utils.agent_config import load_agent_display_name
        names = {}
        for node_name, slug in _NODE_SLUG_MAP.items():
            name = load_agent_display_name(slug)
            if name:
                names[node_name] = name
        names.update(_NODE_DISPLAY_FALLBACK)
        _NODE_DISPLAY_NAMES = names
    return _NODE_DISPLAY_NAMES

logger = logging.getLogger("orchestrator.pipeline")

# 辩论轮次安全上限（与旧 ConditionalLogic.MAX_ROUNDS 一致）
MAX_ROUNDS = 10


@dataclass
class PipelineDeps:
    """pipeline 依赖（由 AnalysisRuntime 构造）"""

    analyst_client: Any  # BaseLLMClient
    debate_client: Any  # BaseLLMClient
    toolkit: Any
    bull_memory: Any = None
    bear_memory: Any = None
    trader_memory: Any = None
    invest_judge_memory: Any = None
    risk_manager_memory: Any = None
    config: Dict[str, Any] = field(default_factory=dict)


def _format_analyst_node(internal_key: str) -> str:
    """internal_key → 节点名（与旧 setup.py 一致，如 'market' → 'Market Analyst'）"""
    return internal_key.replace("_", " ").title().replace(" ", "_") + " Analyst"


def _merge_state_update(target: Dict[str, Any], update: Dict[str, Any]) -> None:
    """顺序合并节点增量（reports 字典合并、messages 追加、errors 追加，其余覆盖）"""
    if not update:
        return
    if "reports" in update and isinstance(update["reports"], dict):
        target["reports"] = {**(target.get("reports") or {}), **update["reports"]}
    if "messages" in update and isinstance(update["messages"], list):
        target.setdefault("messages", [])
        target["messages"].extend(update["messages"])
    for k, v in update.items():
        if k in ("reports", "messages"):
            continue
        target[k] = v


def _report_display_title(report_key: str, display_name: str = "") -> str:
    """report_key → 展示标题。

    解析链：去掉 _report 后缀 → slug 化（bull_researcher_report → bull-researcher）
    → load_agent_display_name(YAML 中文名) → 节点 display_name → report_key 原样。
    """
    base = report_key[: -len("_report")] if report_key.endswith("_report") else report_key
    title = ""
    try:
        from app.engine.agents.utils.agent_config import load_agent_display_name

        title = load_agent_display_name(base.replace("_", "-"))
    except Exception:  # noqa: BLE001 - 标题解析失败回退，不影响事件发射
        title = ""
    return title or display_name or report_key


async def _emit_report_ready(
    event_sink: Optional[Any],
    update: Dict[str, Any],
    *,
    agent_key: str,
    phase: str,
    before_reports: Dict[str, Any],
    display_name: str = "",
) -> None:
    """对比合并前后 reports 字典，为本次 update 中新增/内容变化的报告发射 report_ready。

    前端据此逐份即时展示报告，无需等整阶段结束。事件失败不阻断流水线。
    """
    if event_sink is None:
        return
    try:
        from app.llm.events import REPORT_CONTENT_MAX_CHARS

        reports_update = (update or {}).get("reports")
        if not isinstance(reports_update, dict) or not reports_update:
            return
        for report_key, content in reports_update.items():
            if before_reports.get(report_key) == content:
                continue  # 本次 update 未新增也未变化
            text = content if isinstance(content, str) else str(content)
            await event_sink.emit(
                "report_ready",
                agent_key=agent_key,
                phase=phase,
                report_key=report_key,
                title=_report_display_title(report_key, display_name),
                content=text[:REPORT_CONTENT_MAX_CHARS],
            )
    except Exception as e:  # noqa: BLE001 - 事件发射失败不阻断节点合并
        logger.warning(f"⚠️ [orchestrator] report_ready 发射失败: {e}")


def _record_error(st: Dict[str, Any], node_name: str, error: str, start: float, *, retried: bool) -> None:
    """节点失败落 state["errors"]（不静默吞掉，供前端/回放展示）"""
    st.setdefault("errors", []).append({
        "node": node_name,
        "phase": st.get("_phase", ""),
        "error": error,
        "ts": time.time(),
        "duration_ms": int((time.time() - start) * 1000),
        "retried": retried,
    })


async def run_pipeline(
    deps: PipelineDeps,
    company_name: str,
    trade_date: str,
    selected_analysts: List[str],
    *,
    task_id: Optional[str] = None,
    progress_callback: Optional[Callable[[str], None]] = None,
    event_sink: Optional[Any] = None,
    user_id: Optional[str] = None,
) -> Dict[str, Any]:
    """执行完整分析流水线，返回最终 state（字段形状与旧 final_state 一致）"""
    config = deps.config or {}
    phase2_enabled = bool(config.get("phase2_enabled", False))
    phase3_enabled = bool(config.get("phase3_enabled", False))

    max_debate_rounds = config.get("phase2_debate_rounds")
    if max_debate_rounds is None:
        max_debate_rounds = config.get("max_debate_rounds", 1)
    max_debate_rounds = max(0, min(int(max_debate_rounds), MAX_ROUNDS))
    if not phase2_enabled:
        max_debate_rounds = 0

    max_risk_rounds = config.get("phase3_debate_rounds")
    if max_risk_rounds is None:
        max_risk_rounds = config.get("max_risk_discuss_rounds", 1)
    max_risk_rounds = max(0, min(int(max_risk_rounds), MAX_ROUNDS))
    if not phase3_enabled:
        max_risk_rounds = 0

    # ── MCP 工具（任务级统一发现；新层 MCPManager，pipeline 结束统一关闭）──
    mcp_manager = None
    mcp_tools: List = []
    enable_mcp = bool(getattr(deps.toolkit, "enable_mcp", False))
    if enable_mcp:
        try:
            from app.llm.mcp.client import MCPManager
            from app.llm.mcp.tools import discover_mcp_tools

            mcp_manager = MCPManager()
            mcp_tools = await discover_mcp_tools(mcp_manager)
            # 用户显式选择的 MCP 工具 id 过滤（analysis_service 传入）
            selected_ids = config.get("mcp_tool_ids")
            if selected_ids:
                selected_set = set(selected_ids)
                mcp_tools = [t for t in mcp_tools if t.name in selected_set]
                logger.info(
                    f"🔧 [orchestrator] MCP 工具按选择过滤: {len(mcp_tools)}/{len(selected_set)} 个"
                )
            logger.info(f"🔧 [orchestrator] MCP 工具发现: {len(mcp_tools)} 个")
        except Exception as e:  # noqa: BLE001 - MCP 不可用不阻断分析
            logger.warning(f"⚠️ [orchestrator] MCP 工具发现失败，跳过: {e}")
            mcp_manager = None
            mcp_tools = []

    node_timings: Dict[str, float] = {}

    # 进度单通道：progress_callback 旧兼容入口统一挂到 EventSink.on_progress
    # （无 event_sink 时构造轻量 sink，仅转发进度，不落库不下发）
    if event_sink is None and progress_callback is not None:
        from app.llm.events import EventSink

        event_sink = EventSink(task_id=task_id or "", on_progress=progress_callback)

    def _progress_text(node_name: str) -> str:
        """节点名 → 中文进度消息（映射与旧 _send_progress_update 一致；空串=跳过）"""
        try:
            from app.engine.agents.analysts.dynamic_analyst import DynamicAnalystFactory

            mapping = DynamicAnalystFactory.build_node_mapping()
            message = mapping.get(node_name)
            if message is None:
                return ""  # 跳过（工具节点、消息清理节点）
            return message or f"🔍 {node_name}"
        except Exception as e:  # noqa: BLE001
            logger.warning(f"⚠️ [orchestrator] 进度文案解析失败: {e}")
            return ""

    async def _emit_progress(node_name: str, phase: str = "", agent_key: str = "") -> None:
        if event_sink is None:
            return
        text = _progress_text(node_name)
        if text:
            try:
                # agent_key 缺省用 node_name；调用方应传与生命周期事件一致的键，避免面板分裂出重复 tab
                await event_sink.emit(
                    "progress", agent_key=agent_key or node_name, phase=phase, text=text
                )
            except Exception as e:  # noqa: BLE001
                logger.warning(f"⚠️ [orchestrator] 进度事件发射失败: {e}")

    async def _run_node(
        node_name: str, node_fn, st: Dict[str, Any], event_key: str = "", display_name: str = "",
        critical: bool = False,
    ) -> None:
        """执行单个节点：计时 + 事件 + 失败记录/重试 + 增量合并

        event_key：事件流的 agent_key（用户消息门禁/面板 tab 依据）。
        分析师必须传 internal_key（与 run_conversation 内事件同键），其余阶段默认用
        _NODE_EVENT_KEYS 对齐节点内部 run_conversation 的键（无映射才回退 node_name）。
        display_name：面板展示名（缺省用 node_name）。
        critical：关键节点（Trader/Judge/Manager/Summary）失败自动重试 1 次；
        重试仍失败则记录 errors 并上抛（不再静默吞掉，Summary 终败即整体失败）。
        """
        key = event_key or _NODE_EVENT_KEYS.get(node_name, node_name)
        start = time.time()
        if event_sink is not None:
            event_sink.mark_running(key)
            await event_sink.emit(
                "agent_start", agent_key=key, phase=st.get("_phase", ""),
                name=display_name or _resolve_display_names().get(node_name) or node_name,
            )
            await _emit_progress(node_name, phase=st.get("_phase", ""), agent_key=key)
        try:
            try:
                update = await node_fn(st)
            except Exception as e:  # noqa: BLE001 - 节点异常：先记录再决定重试/上抛
                logger.error(f"❌ [orchestrator] 节点 {node_name} 异常: {e}", exc_info=True)
                if not critical:
                    _record_error(st, node_name, str(e), start, retried=False)
                    update = {}
                else:
                    logger.warning(f"🔁 [orchestrator] 关键节点 {node_name} 失败，重试 1 次")
                    try:
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
                await event_sink.emit(
                    "agent_end", agent_key=key, duration_ms=int(elapsed * 1000)
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
            display_name=display_name or _resolve_display_names().get(node_name) or "",
        )

    state = create_initial_state(company_name, trade_date, task_id=task_id, user_id=user_id)
    # 事件汇聚点经 state 下发（业务节点经 invoker 透传给 run_conversation，Stage 2-4 过程可观测）
    state["_event_sink"] = event_sink

    try:
        try:
            # ── Phase 1：分析师并行（concurrency 可配，=1 等价旧串行）──
            state["_phase"] = "analysts"
            from .agents import build_analyst_specs, run_analyst

            specs = await build_analyst_specs(
                selected_analysts,
                deps.toolkit,
                max_tool_calls=int(config.get("max_tool_calls", 12)),
                mcp_tools=mcp_tools,
                enable_subagent=bool(config.get("enable_subagent", False)),
            )
            concurrency = max(1, int(config.get("analyst_concurrency", 5) or 1))
            semaphore = asyncio.Semaphore(concurrency)

            async def _run_analyst(internal_key: str, spec) -> Dict[str, Any]:
                """单个分析师并行单元：事件/计时/进度 + run_analyst（失败降级）"""
                node_name = _format_analyst_node(internal_key)
                start = time.time()
                if event_sink is not None:
                    event_sink.mark_running(internal_key)
                    await event_sink.emit(
                        "agent_start", agent_key=internal_key, phase="analysts",
                        name=spec.name,
                    )
                    await _emit_progress(node_name, phase="analysts", agent_key=internal_key)
                try:
                    async with semaphore:
                        return await run_analyst(
                            spec, deps.analyst_client, state, event_sink=event_sink
                        )
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
                            "agent_end", agent_key=internal_key,
                            duration_ms=int(elapsed * 1000),
                        )

            analyst_results = await asyncio.gather(
                *[_run_analyst(k, s) for k, s in specs.items()]
            )
            # 按 specs 序回填合并（与旧串行执行的 state 报告顺序一致）
            for (_internal_key, _spec), update in zip(specs.items(), analyst_results):
                _before = dict(state.get("reports") or {})
                _merge_state_update(state, update or {})
                await _emit_report_ready(
                    event_sink, update or {},
                    agent_key=_internal_key, phase="analysts", before_reports=_before,
                )

            # ── Phase 2：公平辩论（Bull 先发言，交替各 rounds+1 次）+ 裁决
            if phase2_enabled:
                state["_phase"] = "research"
                # 与实际循环次数同步（state 初始值为硬编码默认，用于日志分母与 prompt 文案）
                state["investment_debate_state"]["max_rounds"] = max_debate_rounds + 1
                from app.engine.agents.stage_2.research_manager import create_research_manager
                from app.engine.agents.stage_2.researcher_factory import create_researcher

                bull_node = create_researcher(deps.debate_client, deps.bull_memory, side="bull")
                bear_node = create_researcher(deps.debate_client, deps.bear_memory, side="bear")
                research_manager = create_research_manager(deps.debate_client, deps.invest_judge_memory)

                # 总发言 2*(rounds+1)：for 循环展开与旧条件路由 Bull→Bear 交替完全等价
                for _round in range(max_debate_rounds + 1):
                    await _run_node("Bull Researcher", bull_node, state)
                    await _run_node("Bear Researcher", bear_node, state)
                await _run_node("Research Manager", research_manager, state, critical=True)

            # ── Trader（恒执行）──────────────────────────────────────
            state["_phase"] = "trader"
            from app.engine.agents.stage_2.trader import create_trader

            trader_node = create_trader(deps.debate_client, deps.trader_memory)
            await _run_node("Trader", trader_node, state, critical=True)

            # ── Phase 3：风险辩论（固定 Risky→Safe→Neutral 循环）+ 裁决
            if phase3_enabled:
                state["_phase"] = "risk"
                # 同 Phase 2：分母与实际循环次数保持一致
                state["risk_debate_state"]["max_rounds"] = max_risk_rounds + 1
                from app.engine.agents.stage_3.debator_factory import create_debator
                from app.engine.agents.stage_3.risk_manager import create_risk_manager

                debators = {
                    "Risky Analyst": create_debator(deps.debate_client, side="risky"),
                    "Safe Analyst": create_debator(deps.debate_client, side="safe"),
                    "Neutral Analyst": create_debator(deps.debate_client, side="neutral"),
                }
                risk_manager = create_risk_manager(deps.debate_client, deps.risk_manager_memory)

                # 总发言 3*(rounds+1)：固定顺序循环与旧条件路由等价
                for _round in range(max_risk_rounds + 1):
                    for node_name in ("Risky Analyst", "Safe Analyst", "Neutral Analyst"):
                        await _run_node(node_name, debators[node_name], state)
                await _run_node("Risk Judge", risk_manager, state, critical=True)

            # ── Summary（恒执行）─────────────────────────────────────
            state["_phase"] = "summary"
            from app.engine.agents.stage_4.summary_agent import create_summary_agent

            summary_node = create_summary_agent(deps.debate_client)
            # Summary 为终端节点：重试后仍失败则整体失败（不再产出假成功报告）
            await _run_node("Summary Agent", summary_node, state, critical=True)
            if event_sink is not None:
                await event_sink.emit(
                    "progress", agent_key=_NODE_EVENT_KEYS.get("Summary Agent", "Summary Agent"),
                    phase="summary", text="📊 生成报告"
                )

            # reports 字典回填顶层 *_report 字段（支持自定义智能体，与旧逻辑一致）
            for report_key, report_content in (state.get("reports") or {}).items():
                if report_key.endswith("_report") and report_content and not state.get(report_key):
                    state[report_key] = report_content

            state.pop("_phase", None)
            state.pop("_event_sink", None)
            state["node_timings"] = dict(node_timings)
            # 出口重建旧键形状（外部契约不变；内部 rounds 单一数据源）
            return export_legacy_state(state)
        except Exception as e:
            # partial_state 异常语义保留：携带已完成节点的部分结果
            state.pop("_phase", None)
            state.pop("_event_sink", None)
            state["node_timings"] = dict(node_timings)
            e.partial_state = export_legacy_state(state)  # type: ignore[attr-defined]
            raise
    finally:
        if mcp_manager is not None:
            try:
                await mcp_manager.close_all()
            except Exception as e:  # noqa: BLE001
                logger.warning(f"⚠️ [orchestrator] 关闭 MCP 连接失败: {e}")


