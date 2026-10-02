"""P4-b 专项测试：终端契约参数化 + 记忆绑定收尾 + reflector 声明式适配。

覆盖四层：
- 出口信号：_extract_final_signal 点路径探取（spec 声明链优先 / decision_field
  回退 / 旧任务快照无契约时回退内置默认链——与历史硬编码行为逐项一致）
- 编译层：_memory_reflections 声明推导（默认工作流 5 条逐项锚定旧 reflector
  读取口径；自定义 N 方工作流的辩手/裁决条目）+ snapshot 携带 terminal 段
- 输入派生：_reflection_input 对内置槽与旧专用方法读取的派生键逐字一致；
  自定义侧走通用标签视图
- 端到端：terminal judge 提交 fields → final_decision_signal（与内置
  risk-manager 同槽）；反思按声明驱动写入记忆库

驱动方式（项目规则：全真 I/O、禁 mock 底层）：_SubmitClient/_ReflectClient =
BaseLLMClient 真实子类；记忆库用记录型真对象（add_situations 收集入参供断言，
不是被测底层）。
"""

import pytest

from app.engine.runtime import AnalysisRuntime, _extract_final_signal
from app.engine.orchestrator.pipeline import PipelineDeps
from app.engine.orchestrator.state import (
    append_round,
    create_initial_state,
    investment_side_history,
    side_history_labeled,
)
from app.engine.orchestrator.workflow.compiler import CompileParams, compile_workflow
from app.engine.orchestrator.workflow.executor import run_compiled
from app.engine.orchestrator.workflow.loader import load_default_spec
from app.engine.orchestrator.workflow.spec import (
    DebateStage,
    Execution,
    NodeSpec,
    NodeType,
    TerminalSpec,
    WorkflowSpec,
)
from app.llm.core.base import BaseLLMClient, StreamEvent
from app.llm.core.types import (
    ChatResponse,
    Message,
    Role,
    StopReason,
    TextBlock,
    ToolResultBlock,
    ToolUseBlock,
    Usage,
)

# ---------------------------------------------------------------------------
# 出口信号：_extract_final_signal（纯函数）
# ---------------------------------------------------------------------------

_DEFAULT_TERMINAL = {
    "decision_field": "final_trade_decision",
    "signal_fallback": [
        "final_trade_decision",
        "investment_plan",
        "risk_debate_state.judge_decision",
        "trader_investment_plan",
    ],
    "summary_node": "summary",
}


class TestExtractFinalSignal:
    def test_default_chain_equivalence(self):
        """默认链与历史硬编码 or 链行为一致：逐级下探首个非空值"""
        state = {
            "investment_plan": "",
            "risk_debate_state": {"judge_decision": "风险裁决"},
            "trader_investment_plan": "交易计划",
        }
        assert _extract_final_signal(state, _DEFAULT_TERMINAL) == "风险裁决"
        state["investment_plan"] = "投资计划"
        assert _extract_final_signal(state, _DEFAULT_TERMINAL) == "投资计划"
        state["final_trade_decision"] = "最终决策"
        assert _extract_final_signal(state, _DEFAULT_TERMINAL) == "最终决策"

    def test_all_empty_returns_blank(self):
        state = {"final_trade_decision": "", "investment_plan": "", "risk_debate_state": {}}
        assert _extract_final_signal(state, _DEFAULT_TERMINAL) == ""
        assert _extract_final_signal({}, _DEFAULT_TERMINAL) == ""

    def test_custom_fallback_chain_drives_probing(self):
        """自定义工作流声明链：嵌套点路径 + 自定义顶层键按声明序探取"""
        terminal = {
            "decision_field": "panel_decision",
            "signal_fallback": ["panel_decision", "panel_debate_state.judge_decision"],
        }
        state = {"panel_debate_state": {"judge_decision": "裁决正文"}}
        assert _extract_final_signal(state, terminal) == "裁决正文"
        state["panel_decision"] = "最终裁决"
        assert _extract_final_signal(state, terminal) == "最终裁决"

    def test_missing_fallback_falls_back_to_decision_field(self):
        """未声明 signal_fallback → decision_field 单链；再空 → 内置默认链"""
        terminal = {"decision_field": "panel_decision", "signal_fallback": []}
        assert _extract_final_signal({"panel_decision": "裁决"}, terminal) == "裁决"
        # decision_field 也无值 → 回退内置默认链（旧任务快照无契约的兜底）
        assert _extract_final_signal({"trader_investment_plan": "计划"}, terminal) == "计划"
        assert _extract_final_signal({"final_trade_decision": "决策"}, {}) == "决策"


# ---------------------------------------------------------------------------
# 编译层：memory_reflections 声明推导 + snapshot terminal 段
# ---------------------------------------------------------------------------


class TestMemoryReflections:
    def _default_plan(self):
        spec, _ = load_default_spec()
        return compile_workflow(spec, CompileParams(selected_nodes=("market",)))

    def test_default_workflow_five_bindings(self):
        """默认工作流 → 5 条声明，逐项锚定旧 reflector 专用方法的读取口径"""
        plan = self._default_plan()
        by_slot = {r.slot: r for r in plan.memory_reflections}
        assert set(by_slot) == {"bull", "bear", "invest_judge", "trader", "risk_manager"}

        bull = by_slot["bull"]
        assert (bull.kind, bull.state_key, bull.side_key) == ("debater", "investment_debate_state", "bull")
        assert bull.component_key == "BULL"  # 旧 reflect_bull_researcher 的归属口径
        assert bull.label == "多头分析师"  # 旧 bull_history 派生的 argument 标签

        bear = by_slot["bear"]
        assert (bear.kind, bear.state_key, bear.side_key, bear.component_key) == (
            "debater",
            "investment_debate_state",
            "bear",
            "BEAR",
        )

        judge = by_slot["invest_judge"]
        assert (judge.kind, judge.state_key, judge.component_key) == (
            "judge",
            "investment_debate_state",
            "INVEST JUDGE",
        )

        trader = by_slot["trader"]
        assert (trader.kind, trader.report_key, trader.component_key) == ("single", "trader_investment_plan", "TRADER")

        risk = by_slot["risk_manager"]
        assert (risk.kind, risk.state_key, risk.component_key) == ("judge", "risk_debate_state", "RISK JUDGE")

    def test_custom_nside_bindings(self):
        """自定义 N 方组：绑记忆的自定义辩手/裁决按组拓扑入声明（component_key = slug）"""
        default_spec, _ = load_default_spec()
        by_slug = {n.slug: n for n in default_spec.nodes}
        custom = (
            NodeSpec(
                slug="macro-debater",
                type=NodeType.DEBATER,
                execution=Execution.SINGLE_TURN,
                node_name="Macro Debater",
                event_key="macro_debater",
                report_keys=("macro_debater_view",),
                memory="bull",
                builtin=False,
            ),
            NodeSpec(
                slug="panel-judge",
                type=NodeType.JUDGE,
                execution=Execution.SINGLE_TURN,
                node_name="Panel Judge",
                event_key="panel_judge",
                report_keys=("panel_judgement",),
                memory="risk_manager",
                terminal=True,
                builtin=False,
            ),
            NodeSpec(
                slug="bear-researcher",
                type=NodeType.DEBATER,
                execution=Execution.SINGLE_TURN,
                node_name="Bear Researcher",
                event_key="researcher_bear",
                report_keys=("bear_researcher",),
                memory="bear",
                builtin=True,
            ),
        )
        spec = WorkflowSpec(
            slug="p4b-panel",
            name="P4b 测试工作流",
            builtin=False,
            terminal=TerminalSpec(decision_field="panel_decision", summary_node="summary"),
            nodes=(*custom, by_slug["summary"]),
            stages=(
                DebateStage(
                    id="panel_debate",
                    state_key="panel_debate_state",
                    sides=("macro-debater", "bear-researcher"),
                    rounds=1,
                    judge="panel-judge",
                    report_view="generic",
                ),
            ),
        )
        plan = compile_workflow(spec, CompileParams())

        assert len(plan.memory_reflections) == 3
        macro = next(r for r in plan.memory_reflections if r.slot == "bull")
        assert (macro.kind, macro.state_key, macro.side_key) == ("debater", "panel_debate_state", "macro-debater")
        assert macro.component_key == "macro-debater"  # 自定义节点 = slug
        assert macro.label == "Macro Debater"  # 自定义侧标签 = node_name

        judge = next(r for r in plan.memory_reflections if r.slot == "risk_manager")
        assert (judge.kind, judge.state_key, judge.component_key) == ("judge", "panel_debate_state", "panel-judge")

    def test_snapshot_carries_terminal_and_reflections(self):
        """快照携带 terminal 契约与反思声明（P4-b：出口信号/反思从快照读取）"""
        plan = self._default_plan()
        snap = plan.snapshot()
        assert snap["terminal"]["decision_field"] == "final_trade_decision"
        assert snap["terminal"]["signal_fallback"][0] == "final_trade_decision"
        assert {r["slot"] for r in snap["memory_reflections"]} == {
            "bull",
            "bear",
            "invest_judge",
            "trader",
            "risk_manager",
        }
        bull = next(r for r in snap["memory_reflections"] if r["slot"] == "bull")
        assert bull["kind"] == "debater" and bull["side_key"] == "bull"

    def test_no_memory_bindings_when_slots_empty(self):
        """全部节点 memory=null → 空声明（反思自然不触发）"""
        default_spec, _ = load_default_spec()
        stripped = default_spec.model_copy(
            update={"nodes": tuple(n.model_copy(update={"memory": None}) for n in default_spec.nodes)}
        )
        plan = compile_workflow(stripped, CompileParams(selected_nodes=("market",)))
        assert plan.memory_reflections == ()


# ---------------------------------------------------------------------------
# 输入派生：_reflection_input 与旧专用方法读取口径逐字一致
# ---------------------------------------------------------------------------


def _builtin_reflection_state() -> dict:
    """内置工作流形状的最终 state（rounds 单一数据源，含 trader 产出）"""
    state = create_initial_state("000001", "2024-12-31")
    ids = state["investment_debate_state"]
    append_round(ids, "bull", "bull 初始论点。", 2)
    append_round(ids, "bear", "bear 初始论点。", 2)
    append_round(ids, "bull", "bull 反驳。", 2)
    append_round(ids, "bear", "bear 反驳。", 2)
    ids["judge_decision"] = "研究裁决结论。"
    rds = state["risk_debate_state"]
    append_round(rds, "risky", "激进观点。", 3)
    append_round(rds, "safe", "保守观点。", 3)
    append_round(rds, "neutral", "中性观点。", 3)
    rds["judge_decision"] = "风控裁决结论。"
    state["trader_investment_plan"] = "交易员投资计划。"
    return state


class TestReflectionInput:
    def test_builtin_debater_matches_legacy_derived_key(self):
        """bull 条目派生文本 == 旧 reflect_bull_researcher 读取的 bull_history（export 派生键）"""
        state = _builtin_reflection_state()
        entry = {"kind": "debater", "state_key": "investment_debate_state", "side_key": "bull", "label": "多头分析师"}
        derived = AnalysisRuntime._reflection_input(state, entry)
        assert derived == investment_side_history(state["investment_debate_state"], "bull")
        assert "# 【多头分析师 - 初始报告】" in derived
        assert "# 【多头分析师 - 第 1 轮辩论】" in derived

    def test_builtin_judge_and_single_entries(self):
        state = _builtin_reflection_state()
        judge = AnalysisRuntime._reflection_input(state, {"kind": "judge", "state_key": "risk_debate_state"})
        assert judge == "风控裁决结论。"
        single = AnalysisRuntime._reflection_input(state, {"kind": "single", "report_key": "trader_investment_plan"})
        assert single == "交易员投资计划。"

    def test_single_entry_prefers_blackboard(self):
        """single 条目黑板优先、顶层回退（自定义 single 节点产出落 reports 黑板）"""
        state = {"reports": {"custom_decision": "黑板版本"}, "custom_decision": ""}
        entry = {"kind": "single", "report_key": "custom_decision"}
        assert AnalysisRuntime._reflection_input(state, entry) == "黑板版本"

    def test_custom_debater_uses_label_view(self):
        """自定义侧：label=node_name 的通用 argument 视图（N 方组反思可用）"""
        ds = {"rounds": [], "count": 0}
        # per_turn=2 交替双侧，保证 macro 两轮发言分落 rounds[0]/rounds[1]
        append_round(ds, "macro-debater", "宏观首轮。", 2)
        append_round(ds, "bear", "bear 首轮。", 2)
        append_round(ds, "macro-debater", "宏观反驳。", 2)
        append_round(ds, "bear", "bear 反驳。", 2)
        entry = {
            "kind": "debater",
            "state_key": "panel_debate_state",
            "side_key": "macro-debater",
            "label": "Macro Debater",
        }
        out = AnalysisRuntime._reflection_input({"panel_debate_state": ds}, entry)
        assert out == side_history_labeled(ds, "macro-debater", "Macro Debater")
        assert "# 【Macro Debater - 初始报告】\n宏观首轮。" in out
        assert "# 【Macro Debater - 第 1 轮辩论】\n宏观反驳。" in out
        assert "bear 首轮。" not in out  # 他侧内容不串入

    def test_empty_inputs_yield_blank(self):
        assert (
            AnalysisRuntime._reflection_input({}, {"kind": "debater", "state_key": "x", "side_key": "y", "label": "Y"})
            == ""
        )
        assert AnalysisRuntime._reflection_input({}, {"kind": "judge", "state_key": "x"}) == ""
        assert AnalysisRuntime._reflection_input({}, {"kind": "single", "report_key": "k"}) == ""
        assert AnalysisRuntime._reflection_input({}, {"kind": "unknown"}) == ""


# ---------------------------------------------------------------------------
# 端到端：terminal judge 信号槽 + 出口探取（真实执行）
# ---------------------------------------------------------------------------


class _SubmitClient(BaseLLMClient):
    """terminal judge 提交结构化决策参数（submit_report），其余会话文本回复。"""

    protocol = "test"
    model = "test-p4b-model"

    def __init__(self):
        self.sessions: list = []

    async def chat_stream(self, messages, *, system=None, tools=None, **kwargs):
        last = messages[-1] if messages else None
        is_tool_result = (
            last is not None and last.role == Role.USER and any(isinstance(b, ToolResultBlock) for b in last.blocks())
        )
        if not is_tool_result:
            self.sessions.append(system or "")
            resp = ChatResponse(
                message=Message(
                    role=Role.ASSISTANT,
                    content=[
                        TextBlock(text="裁决如下。"),
                        ToolUseBlock(
                            id="toolu_p4b_1",
                            name="submit_report",
                            input={
                                "content": "panel 最终裁决正文。",
                                "action": "卖出",
                                "target_price": 9.9,
                                "confidence": 0.66,
                                "risk_score": 0.7,
                                "reasoning": "综合四方观点",
                            },
                        ),
                    ],
                ),
                stop_reason=StopReason.TOOL_USE,
                usage=Usage(input_tokens=10, output_tokens=5),
                model=self.model,
            )
        else:
            resp = ChatResponse(
                message=Message(role=Role.ASSISTANT, content=[TextBlock(text="已提交。")]),
                stop_reason=StopReason.END_TURN,
                usage=Usage(input_tokens=10, output_tokens=5),
                model=self.model,
            )
        yield StreamEvent("message", response=resp)

    async def chat(self, messages, **kwargs) -> ChatResponse:
        return ChatResponse(
            message=Message(role=Role.ASSISTANT, content=[TextBlock(text="文本回复。")]),
            stop_reason=StopReason.END_TURN,
            usage=Usage(input_tokens=10, output_tokens=5),
            model=self.model,
        )

    async def count_tokens(self, messages) -> int:
        return 16


class TestTerminalSignalEndToEnd:
    async def test_terminal_judge_writes_signal_and_exit_probes_contract(self, custom_p4b_agents):
        """terminal judge 提交 fields → final_decision_signal（与内置 risk-manager 同槽）；
        出口按快照 terminal 契约探取 panel_decision"""
        default_spec, _ = load_default_spec()
        by_slug = {n.slug: n for n in default_spec.nodes}
        spec = WorkflowSpec(
            slug="p4b-e2e",
            name="P4b 端到端工作流",
            builtin=False,
            terminal=TerminalSpec(
                decision_field="panel_decision",
                signal_fallback=("panel_decision", "panel_debate_state.judge_decision"),
                summary_node="summary",
            ),
            nodes=(
                NodeSpec(
                    slug="macro-debater",
                    type=NodeType.DEBATER,
                    execution=Execution.SINGLE_TURN,
                    node_name="Macro Debater",
                    event_key="macro_debater",
                    report_keys=("macro_debater_view",),
                    builtin=False,
                ),
                NodeSpec(
                    slug="bear-researcher",
                    type=NodeType.DEBATER,
                    execution=Execution.SINGLE_TURN,
                    node_name="Bear Researcher",
                    event_key="researcher_bear",
                    report_keys=("bear_researcher",),
                    builtin=True,
                ),
                NodeSpec(
                    slug="panel-judge",
                    type=NodeType.JUDGE,
                    execution=Execution.SINGLE_TURN,
                    node_name="Panel Judge",
                    event_key="panel_judge",
                    report_keys=("panel_judgement",),
                    terminal=True,
                    builtin=False,
                ),
                by_slug["summary"],
            ),
            stages=(
                DebateStage(
                    id="panel_debate",
                    state_key="panel_debate_state",
                    sides=("macro-debater", "bear-researcher"),
                    rounds=1,
                    judge="panel-judge",
                    report_view="generic",
                ),
            ),
        )
        plan = compile_workflow(spec, CompileParams())
        client = _SubmitClient()
        state = create_initial_state("000001", "2024-12-31")
        state["_plan_snapshot"] = plan.snapshot()
        deps = PipelineDeps(analyst_client=client, debate_client=client, toolkit=None, config={})
        await run_compiled(plan, deps, state, event_sink=None, mcp_tools=[], node_timings={})

        # terminal 决策字段 + 结构化信号槽（submit 协议一手来源）
        assert state["panel_decision"] == "panel 最终裁决正文。"
        signal = state["final_decision_signal"]
        assert signal["action"] == "卖出"
        assert signal["target_price"] == 9.9

        # 出口信号：按快照 terminal 契约探取（点路径链）
        terminal = state["_plan_snapshot"]["terminal"]
        assert _extract_final_signal(state, terminal) == "panel 最终裁决正文。"
        state.pop("panel_decision", None)  # 首选缺失 → 下探嵌套路径
        assert _extract_final_signal(state, terminal) == "panel 最终裁决正文。"


@pytest.fixture
def custom_p4b_agents(mongodb_available):
    """agent_specs 插入 2 个自定义条目（macro-debater / panel-judge），用例后清理。"""
    from datetime import datetime, timezone

    from app.engine.orchestrator.workflow import store

    slugs = ["macro-debater", "panel-judge"]
    now = datetime.now(timezone.utc)
    docs = [
        {
            "_id": "macro-debater",
            "phase": 2,
            "position": 910,
            "builtin": False,
            "deleted": False,
            "created_at": now,
            "updated_at": now,
            "spec": {"slug": "macro-debater", "name": "宏观辩手", "roleDefinition": "你是宏观辩手。"},
        },
        {
            "_id": "panel-judge",
            "phase": 2,
            "position": 911,
            "builtin": False,
            "deleted": False,
            "created_at": now,
            "updated_at": now,
            "spec": {"slug": "panel-judge", "name": "裁决官", "roleDefinition": "你是辩论裁决官。"},
        },
    ]
    coll = store._db()[store.AGENT_SPECS_COLLECTION]
    coll.delete_many({"_id": {"$in": slugs}})
    coll.insert_many(docs)
    store.invalidate_store_cache()
    yield
    coll.delete_many({"_id": {"$in": slugs}})
    store.invalidate_store_cache()


# ---------------------------------------------------------------------------
# 端到端：反思按声明驱动写入记忆库
# ---------------------------------------------------------------------------


class _ReflectClient(BaseLLMClient):
    """反思会话客户端：普通对话文本回复（无工具）。"""

    protocol = "test"
    model = "test-reflect-model"

    def __init__(self):
        self.prompts: list = []

    async def chat_stream(self, messages, *, system=None, tools=None, **kwargs):
        self.prompts.append("\n".join(getattr(b, "text", "") or "" for m in messages for b in m.blocks()))
        resp = ChatResponse(
            message=Message(role=Role.ASSISTANT, content=[TextBlock(text="本次决策的经验总结。")]),
            stop_reason=StopReason.END_TURN,
            usage=Usage(input_tokens=10, output_tokens=5),
            model=self.model,
        )
        yield StreamEvent("message", response=resp)

    async def chat(self, messages, **kwargs) -> ChatResponse:
        return ChatResponse(
            message=Message(role=Role.ASSISTANT, content=[TextBlock(text="文本回复。")]),
            stop_reason=StopReason.END_TURN,
            usage=Usage(input_tokens=10, output_tokens=5),
            model=self.model,
        )

    async def count_tokens(self, messages) -> int:
        return 16


class _RecordingMemory:
    """记录型记忆库（真对象：收集 add_situations 入参供断言）"""

    def __init__(self):
        self.situations = []

    def add_situations(self, items):
        self.situations.extend(items)


class TestReflectAndRemember:
    def _runtime_with(self, state: dict) -> tuple:
        runtime = AnalysisRuntime(selected_analysts=["market"], config={"memory_enabled": False})
        runtime.curr_state = state
        client = _ReflectClient()
        from app.engine.agents.postprocess.reflector import Reflector

        runtime._reflector = Reflector(client, task_id=state.get("task_id") or "")
        memories = {slot: _RecordingMemory() for slot in ("bull", "bear", "invest_judge", "trader", "risk_manager")}
        for slot, mem in memories.items():
            setattr(runtime, f"{slot}_memory", mem)
        return runtime, client, memories

    async def test_default_workflow_reflects_all_bindings(self):
        """内置 5 槽全部声明且输入非空 → 5 次反思各自写入对应记忆库"""
        state = _builtin_reflection_state()
        spec, _ = load_default_spec()
        plan = compile_workflow(spec, CompileParams(selected_nodes=("market",)))
        state["_plan_snapshot"] = plan.snapshot()

        runtime, client, memories = self._runtime_with(state)
        await runtime.reflect_and_remember({"ret": 0.05})

        assert len(client.prompts) == 5
        for slot, mem in memories.items():
            assert len(mem.situations) == 1, f"{slot} 记忆库应写入一次"
            situation, lesson = mem.situations[0]
            assert lesson == "本次决策的经验总结。"
        # trader 反思 prompt 含其决策文本
        assert any("交易员投资计划。" in p for p in client.prompts)

    async def test_empty_inputs_skip_reflection(self):
        """输入为空的绑定跳过（P4-b 行为变更：不再对空历史发起无意义 LLM 反思）"""
        state = create_initial_state("000001", "2024-12-31")  # 辩论 rounds 空、trader 计划空
        spec, _ = load_default_spec()
        plan = compile_workflow(spec, CompileParams(selected_nodes=("market",)))
        state["_plan_snapshot"] = plan.snapshot()

        runtime, client, memories = self._runtime_with(state)
        await runtime.reflect_and_remember({"ret": 0.0})

        assert client.prompts == []
        assert all(not mem.situations for mem in memories.values())

    async def test_custom_workflow_reflects_nside_bindings(self):
        """自定义 N 方工作流：绑记忆的自定义辩手/裁决同样入反思（声明驱动）"""
        state = create_initial_state("000001", "2024-12-31")
        ds: dict = {"rounds": [], "count": 0}
        append_round(ds, "macro-debater", "宏观初始观点。", 2)
        append_round(ds, "bear", "bear 初始观点。", 2)
        ds["judge_decision"] = "panel 裁决。"
        state["panel_debate_state"] = ds
        state["_plan_snapshot"] = {
            "memory_reflections": [
                {
                    "slot": "bull",
                    "component_key": "macro-debater",
                    "kind": "debater",
                    "state_key": "panel_debate_state",
                    "side_key": "macro-debater",
                    "label": "Macro Debater",
                },
                {
                    "slot": "risk_manager",
                    "component_key": "panel-judge",
                    "kind": "judge",
                    "state_key": "panel_debate_state",
                },
            ]
        }

        runtime, client, memories = self._runtime_with(state)
        await runtime.reflect_and_remember({"ret": -0.02})

        assert len(client.prompts) == 2
        assert len(memories["bull"].situations) == 1
        assert len(memories["risk_manager"].situations) == 1
        # 自定义辩手的反思输入 = 带标签发言史
        assert any("# 【Macro Debater - 初始报告】" in p for p in client.prompts)
        assert any("panel 裁决。" in p for p in client.prompts)

    async def test_no_snapshot_reflections_noop(self):
        """旧任务快照无 memory_reflections 段 → 反思不触发（安全降级）"""
        state = _builtin_reflection_state()
        state["_plan_snapshot"] = {"workflow_slug": "default-4stage"}
        runtime, client, memories = self._runtime_with(state)
        await runtime.reflect_and_remember({"ret": 0.0})
        assert client.prompts == []
        assert all(not mem.situations for mem in memories.values())
