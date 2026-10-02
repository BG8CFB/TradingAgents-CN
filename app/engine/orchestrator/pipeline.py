"""
保序流水线（替代 LangGraph graph/setup.py 的编排）

硬约束（语义与旧图等价，禁止漂移）：
- Phase 1 分析师并行（Semaphore(analyst_concurrency)，模型级 max_concurrency 封顶）
- Phase 2 公平辩论：同轮 Bull/Bear 并行 + barrier（debate_parallel=False 回退串行交替），
  各发言 rounds+1 次，总发言上限 2*(rounds+1)；公平性 = 上下文注入只读完整历史轮
  （rounds[0:current_round_index]），与旧串行逐字节一致
- Trader 恒执行（phase2 关闭时直接从分析师进入）
- Phase 3 风险辩论：同轮三方并行 + barrier（回退固定 Risky→Safe→Neutral 串行），
  总发言上限 3*(rounds+1)
- Summary 恒执行
- phase2/phase3 开关三拓扑：P2+P3 / P2 / 仅 P3(P2 关→分析师直连 Trader)
"""

import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

import logging

from . import registry
from .state import create_initial_state, export_legacy_state

# 身份映射（节点名 ↔ slug/event_key/显示名/报告标题）的单一权威来源 = registry：
# 旧四张模块级映射表已收敛（等价证明见 tests/engine/test_registry.py），
# agent_key 保持英文稳定标识（历史事件兼容与用户消息门禁稳定）。

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
    # 模型级并发限额（providers bundle._meta 透传；None=不限）
    analyst_limit: Optional[int] = None
    analyst_limit_key: Optional[str] = None
    debate_limit: Optional[int] = None
    debate_limit_key: Optional[str] = None


def _format_analyst_node(internal_key: str) -> str:
    """internal_key → 节点名（与旧 setup.py 一致，如 'market' → 'Market Analyst'）"""
    return registry.format_analyst_node(internal_key)


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
    """report_key → 展示标题（委托 registry 单一权威表）。

    解析链：去掉 _report 后缀 → 别名索引/slug 化（bull_researcher → bull-researcher）
    → YAML 中文名（原 slug 与 +\"-analyst\" 后缀双候选——Stage 1 报告键不带后缀而
    YAML slug 带，如 social_media_report → social-media-analyst）→ display_name
    → report_key 原样。等价证明见 tests/engine/test_registry.py。
    """
    return registry.report_title(report_key, display_name)


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


def _merge_debate_updates(
    st: Dict[str, Any],
    updates: List[Dict[str, Any]],
    *,
    state_key: str,
    side_keys: List[str],
    has_latest_speaker: bool = False,
) -> List[str]:
    """辩论 barrier 合并（纯函数，就地修改 st）：并行各侧 update → 字段级写入 debate_state。

    - rounds[idx][side_key] 按侧写入（idx 用合并前快照 count//per_turn，避免读改写竞争）
    - count = 快照 + 成功侧数（失败侧缺席该轮，与串行失败语义一致）
    - 各 update 的非 debate_state 键（messages/reports/errors）按固定侧序合并（确定性）
    - Phase 3 latest_speaker = 固定顺序中最后一个有产出的侧（旧串行轮末等价）
    返回成功产出内容的 side_key 列表（固定顺序）。
    """
    from .state import current_round_index

    ds = st.setdefault(state_key, {})
    snapshot_count = int(ds.get("count", 0) or 0)
    snapshot_idx = current_round_index(ds, len(side_keys))
    succeeded: List[str] = []
    last_written: Optional[str] = None
    for side_key, update in zip(side_keys, updates):
        new_ds = (update or {}).get(state_key)
        content = None
        if isinstance(new_ds, dict):
            new_rounds = new_ds.get("rounds") or []
            if snapshot_idx < len(new_rounds):
                content = new_rounds[snapshot_idx].get(side_key)
        if content:
            rounds: List[Dict[str, Any]] = ds.setdefault("rounds", [])
            while snapshot_idx >= len(rounds):
                rounds.append({})
            rounds[snapshot_idx][side_key] = content
            succeeded.append(side_key)
            last_written = side_key
        _merge_state_update(st, {k: v for k, v in (update or {}).items() if k != state_key})
    ds["count"] = snapshot_count + len(succeeded)
    if has_latest_speaker and last_written is not None:
        ds["latest_speaker"] = last_written
    return succeeded


def _record_error(st: Dict[str, Any], node_name: str, error: str, start: float, *, retried: bool) -> None:
    """节点失败落 state["errors"]（不静默吞掉，供前端/回放展示）"""
    st.setdefault("errors", []).append(
        {
            "node": node_name,
            "phase": st.get("_phase", ""),
            "error": error,
            "ts": time.time(),
            "duration_ms": int((time.time() - start) * 1000),
            "retried": retried,
        }
    )


def interpolate_percent(completed: int, total: int, lo: int, hi: int) -> int:
    """completed/total 线性映射到 [lo, hi]；total<=0 返回 lo，完成时恰为 hi（尾差归末端）"""
    if total <= 0 or completed <= 0:
        return lo
    if completed >= total:
        return hi
    return lo + round(completed / total * (hi - lo))


async def run_pipeline(
    deps: PipelineDeps,
    company_name: str,
    trade_date: str,
    selected_analysts: List[str],
    *,
    task_id: Optional[str] = None,
    progress_callback: Optional[Callable[[Any], None]] = None,
    event_sink: Optional[Any] = None,
    user_id: Optional[str] = None,
    progress_range: tuple = (0, 100),
) -> Dict[str, Any]:
    """执行完整分析流水线，返回最终 state（字段形状与旧 final_state 一致）。

    编排（2026-09 工作流通用化）：加载工作流 spec（DB 权威）→ 旧 API 配置映射为
    CompileParams → compile 冻结执行计划（快照随 state 下发，在跑任务不受编辑影响）
    → executor 按 plan 遍历阶段。阶段拓扑不再写死在本函数。
    """
    config = deps.config or {}

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
                logger.info(f"🔧 [orchestrator] MCP 工具按选择过滤: {len(mcp_tools)}/{len(selected_set)} 个")
            logger.info(f"🔧 [orchestrator] MCP 工具发现: {len(mcp_tools)} 个")
        except Exception as e:  # noqa: BLE001 - MCP 不可用不阻断分析
            logger.warning(f"⚠️ [orchestrator] MCP 工具发现失败，跳过: {e}")
            # 失败也必须显式关闭已建立的 stdio 会话：泄漏的 anyio cancel scope
            # 被 GC 关闭时会以 CancelledError 反杀整个流水线（BaseException 穿透 except Exception）
            if mcp_manager is not None:
                try:
                    await mcp_manager.close_all()
                except Exception as close_err:  # noqa: BLE001
                    logger.warning(f"⚠️ [orchestrator] MCP 会话关闭失败: {close_err}")
            mcp_manager = None
            mcp_tools = []

    node_timings: Dict[str, float] = {}

    # 进度单通道：progress_callback 旧兼容入口统一挂到 EventSink.on_progress
    # （无 event_sink 时构造轻量 sink，仅转发进度，不落库不下发）
    if event_sink is None and progress_callback is not None:
        from app.llm.events import EventSink

        event_sink = EventSink(task_id=task_id or "", on_progress=progress_callback)

    state = create_initial_state(company_name, trade_date, task_id=task_id, user_id=user_id)
    # 事件汇聚点经 state 下发（业务节点经 invoker 透传给 run_conversation，Stage 2-4 过程可观测）
    state["_event_sink"] = event_sink

    try:
        try:
            # ── 工作流编译（延迟 import 避免 pipeline ↔ workflow.executor 模块级循环）──
            from .workflow.compiler import compile_workflow, params_from_legacy_config
            from .workflow.executor import run_compiled
            from .workflow.loader import check_required_inputs, default_workflow_slug, load_workflow_by_slug

            # P5-c：任务级 workflow_slug（缺省=默认工作流）；加载失败 fail-fast 不静默回退
            workflow_slug = config.get("workflow_slug") or default_workflow_slug()
            spec, spec_hash = load_workflow_by_slug(workflow_slug)
            params = params_from_legacy_config(config, selected_analysts)
            plan = compile_workflow(spec, params, spec_hash=spec_hash)
            # required 输入 fail-fast（§4.6 L263 行为变更）：裁掉必需分析师在编译期
            # 拒绝任务（此前静默跑出劣质报告）；契约读 agent_specs 库
            required_errors = check_required_inputs(spec, plan)
            if required_errors:
                from .workflow.compiler import CompileError

                raise CompileError("；".join(required_errors))
            # 执行计划快照：任务启动即冻结（spec_hash + params），编辑库中 spec/智能体
            # 不影响在跑任务；随 state 导出，由服务层持久化到 workflow_snapshot 字段
            state["_plan_snapshot"] = plan.snapshot()

            await run_compiled(
                plan,
                deps,
                state,
                event_sink=event_sink,
                mcp_tools=mcp_tools,
                node_timings=node_timings,
                progress_range=progress_range,
            )

            # reports 字典回填顶层 *_report 字段（支持自定义智能体，与旧逻辑一致）
            for report_key, report_content in (state.get("reports") or {}).items():
                if report_key.endswith("_report") and report_content and not state.get(report_key):
                    state[report_key] = report_content

            state.pop("_phase", None)
            state.pop("_event_sink", None)
            state.pop("_stage_inputs", None)
            state["node_timings"] = dict(node_timings)
            # 出口重建旧键形状（外部契约不变；内部 rounds 单一数据源）
            return export_legacy_state(state)
        except Exception as e:
            # partial_state 异常语义保留：携带已完成节点的部分结果
            state.pop("_phase", None)
            state.pop("_event_sink", None)
            state.pop("_stage_inputs", None)
            state["node_timings"] = dict(node_timings)
            e.partial_state = export_legacy_state(state)  # type: ignore[attr-defined]
            raise
    finally:
        if mcp_manager is not None:
            try:
                await mcp_manager.close_all()
            except Exception as e:  # noqa: BLE001
                logger.warning(f"⚠️ [orchestrator] 关闭 MCP 连接失败: {e}")
