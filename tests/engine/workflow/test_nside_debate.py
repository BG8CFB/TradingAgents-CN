"""辩论 N 方泛化专项测试（P4-a，设计文档 §4.4 DebateStage / L542 / L548）。

覆盖四层：
- 编译层：4 方辩论 spec（2 内置研究员 + 2 自定义辩手 + 自定义 terminal judge）
  通过 validator + compile，计划形状与进度原子数正确
- 合并层：_merge_debate_updates 的 per_turn=4 语义（公平轮键集 / 失败侧缺席 /
  count 快照 + 成功数 / latest_speaker 开关）——设计文档 L548 指定的专项回归
- 视图层：make_generic_report_content 带标签视图 / generic_report_content 回退版
- 端到端：自定义 state_key + generic 视图的 4 方工作流经 run_compiled 真实执行
  （submit_report 协议驱动；parallel / serial 双路径；轮次公平性历史注入断言）

驱动方式（项目规则：全真 I/O、禁 mock 底层）：_NSideClient = BaseLLMClient
真实子类（按「messages 末条 USER 是否为工具结果」驱动提交状态机），会话首调
记录完整 prompt 文本（公平性注入断言的数据源）。
"""

from datetime import datetime, timezone

import pytest

from app.engine.orchestrator.pipeline import PipelineDeps, _merge_debate_updates
from app.engine.orchestrator.state import (
    append_round,
    create_initial_state,
    generic_report_content,
    make_generic_report_content,
)
from app.engine.orchestrator.workflow.compiler import compile_workflow
from app.engine.orchestrator.workflow.executor import run_compiled
from app.engine.orchestrator.workflow.loader import load_default_spec
from app.engine.orchestrator.workflow.spec import (
    CompileParams,
    DebateStage,
    Execution,
    NodeSpec,
    NodeType,
    TerminalSpec,
    WorkflowSpec,
)
from app.engine.orchestrator.workflow.validator import validate_or_raise
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

CUSTOM_SLUGS = ("macro-debater", "quant-debater", "panel-judge")
SIDES = ("bull-researcher", "bear-researcher", "macro-debater", "quant-debater")
SIDE_KEYS = ("bull", "bear", "macro-debater", "quant-debater")
STATE_KEY = "panel_debate_state"
SUBMITTED = "N方辩论观点正文。"


# ---------------------------------------------------------------------------
# 测试工作流 spec：4 方辩论（2 内置 + 2 自定义）+ terminal judge
# ---------------------------------------------------------------------------


def _panel_workflow_spec() -> WorkflowSpec:
    """4 方辩论工作流：内置 bull/bear NodeSpec 复用默认 spec（锚点一致），
    自定义辩手 / terminal judge 为 builtin=False 条目。"""
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
            builtin=False,
        ),
        NodeSpec(
            slug="quant-debater",
            type=NodeType.DEBATER,
            execution=Execution.SINGLE_TURN,
            node_name="Quant Debater",
            event_key="quant_debater",
            report_keys=("quant_debater_view",),
            builtin=False,
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
    )
    return WorkflowSpec(
        slug="nside-panel",
        name="N方辩论测试工作流",
        builtin=False,
        terminal=TerminalSpec(decision_field="panel_decision", summary_node="summary"),
        nodes=(by_slug["bull-researcher"], by_slug["bear-researcher"], by_slug["summary"], *custom),
        stages=(
            DebateStage(
                id="panel_debate",
                event_phase="panel",
                state_key=STATE_KEY,
                sides=SIDES,
                rounds=1,
                judge="panel-judge",
                report_view="generic",
            ),
        ),
    )


def _compiled_panel_plan():
    spec = _panel_workflow_spec()
    validate_or_raise(spec)
    return compile_workflow(spec, CompileParams())


# ---------------------------------------------------------------------------
# scripted client（真实子类；会话首调记录 prompt 文本供公平性断言）
# ---------------------------------------------------------------------------


def _last_is_tool_result(messages) -> bool:
    last = messages[-1]
    return last.role == Role.USER and any(isinstance(b, ToolResultBlock) for b in last.blocks())


def _prompt_text(system, messages) -> str:
    parts = [system or ""]
    for m in messages:
        for b in m.blocks():
            parts.append(getattr(b, "text", "") or "")
    return "\n".join(parts)


class _NSideClient(BaseLLMClient):
    """首轮提交超集合法参数、收到工具结果后收尾；sessions 记录每会话首调 prompt。"""

    protocol = "test"
    model = "test-nside-model"

    def __init__(self, content: str = SUBMITTED):
        self.sessions: list = []
        self._content = content

    async def chat_stream(self, messages, *, system=None, tools=None, **kwargs):
        if not _last_is_tool_result(messages):
            self.sessions.append(_prompt_text(system, messages))
            resp = self._tool_resp()
        else:
            resp = self._text_resp("已提交，收尾。")
        yield StreamEvent("message", response=resp)

    async def chat(self, messages, **kwargs) -> ChatResponse:
        return self._text_resp("已提交，收尾。")

    async def count_tokens(self, messages) -> int:
        return 16

    def _tool_resp(self) -> ChatResponse:
        # 超集提交参数：debater/judge/terminal 各 node_type 的必填字段全覆盖
        return ChatResponse(
            message=Message(
                role=Role.ASSISTANT,
                content=[
                    TextBlock(text="观点如下，现提交。"),
                    ToolUseBlock(
                        id="toolu_nside_1",
                        name="submit_report",
                        input={
                            "content": self._content,
                            "action": "买入",
                            "target_price": 12.5,
                            "confidence": 0.8,
                            "risk_score": 0.3,
                            "reasoning": "综合各方观点",
                            "key_indicators": {"entry_price": "10"},
                            "model_confidence": 88,
                            "final_signal": "Buy",
                        },
                    ),
                ],
            ),
            stop_reason=StopReason.TOOL_USE,
            usage=Usage(input_tokens=10, output_tokens=5),
            model=self.model,
        )

    def _text_resp(self, text: str) -> ChatResponse:
        return ChatResponse(
            message=Message(role=Role.ASSISTANT, content=[TextBlock(text=text)]),
            stop_reason=StopReason.END_TURN,
            usage=Usage(input_tokens=10, output_tokens=5),
            model=self.model,
        )


class _PromptSink:
    """事件捕获 sink（与 pipeline 消费的 EventSink 接口兼容）"""

    def __init__(self):
        self.events: list = []

    async def emit(self, event_type: str, **fields):
        self.events.append({"event_type": event_type, **fields})

    def mark_running(self, key: str):
        pass

    def mark_completed(self, key: str):
        pass


# ---------------------------------------------------------------------------
# 编译层
# ---------------------------------------------------------------------------


class TestNSideCompile:
    def test_compile_four_side_plan(self):
        from app.engine.orchestrator.workflow.plan import PlannedDebate

        plan = _compiled_panel_plan()
        (stage,) = plan.stages
        assert isinstance(stage, PlannedDebate)
        assert [n.slug for n in stage.sides] == list(SIDES)
        assert stage.judge.slug == "panel-judge"
        assert stage.judge.terminal is True  # terminal 契约编译期冻结
        assert stage.state_key == STATE_KEY
        assert stage.report_view == "generic"
        assert stage.rounds == 1
        # 进度原子：4 侧 × (1+1 轮) + judge = 9
        assert plan.total_units() == 9

    def test_validator_accepts_custom_nside(self):
        """自定义工作流（builtin=False）引用内置节点子集：结构校验通过，
        锚点校验按 spec.builtin 分流不强制 registry 全集"""
        spec = _panel_workflow_spec()
        validate_or_raise(spec)  # 不抛即通过

    def test_validator_rejects_two_few_sides(self):
        from app.engine.orchestrator.workflow.validator import WorkflowValidationError, validate

        spec = _panel_workflow_spec()
        broken = spec.model_copy(
            update={
                "stages": (
                    DebateStage(
                        id="panel_debate",
                        state_key=STATE_KEY,
                        sides=("bull-researcher",),
                        judge="panel-judge",
                    ),
                )
            }
        )
        with pytest.raises(WorkflowValidationError):
            validate_or_raise(broken)
        assert any("至少 2 方" in e for e in validate(broken))


# ---------------------------------------------------------------------------
# 合并层：_merge_debate_updates 的 per_turn=4 公平性语义（设计文档 L548 专项）
# ---------------------------------------------------------------------------


def _side_update(base_ds: dict, side_key: str, content: str, per_turn: int = 4) -> dict:
    """构造一侧的辩论 update（基于同一合并前快照构造，模拟并行各侧）"""
    ds = dict(base_ds)
    rounds = [dict(r) for r in base_ds.get("rounds", [])]
    ds["rounds"] = rounds
    append_round(ds, side_key, content, per_turn)
    return {STATE_KEY: ds}


class TestMergeFairness:
    def _fresh_state(self) -> dict:
        return {STATE_KEY: {"rounds": [], "count": 0}}

    def test_four_sides_complete_round(self):
        st = self._fresh_state()
        base = st[STATE_KEY]
        updates = [_side_update(base, sk, f"{sk}-R0") for sk in SIDE_KEYS]

        succeeded = _merge_debate_updates(st, updates, state_key=STATE_KEY, side_keys=list(SIDE_KEYS))

        ds = st[STATE_KEY]
        assert succeeded == list(SIDE_KEYS)  # 固定侧序
        assert set(ds["rounds"][0]) == set(SIDE_KEYS)  # 一轮键集完整
        assert ds["count"] == 4  # 快照 0 + 成功 4

    def test_failed_side_absent(self):
        """失败侧 update 无 debate_state → 该轮缺席、count 只加成功数"""
        st = self._fresh_state()
        base = st[STATE_KEY]
        updates = [
            _side_update(base, "bull", "bull-R0"),
            {},  # bear 失败（无产出）
            _side_update(base, "macro-debater", "macro-R0"),
            _side_update(base, "quant-debater", "quant-R0"),
        ]

        succeeded = _merge_debate_updates(st, updates, state_key=STATE_KEY, side_keys=list(SIDE_KEYS))

        ds = st[STATE_KEY]
        assert succeeded == ["bull", "macro-debater", "quant-debater"]
        assert set(ds["rounds"][0]) == {"bull", "macro-debater", "quant-debater"}
        assert ds["count"] == 3

    def test_next_round_index_advances(self):
        """count 达 4（per_turn=4）后下一批写入 rounds[1]（快照 idx = count//per_turn）"""
        st = {STATE_KEY: {"rounds": [dict.fromkeys(SIDE_KEYS, "R0")], "count": 4}}
        base = st[STATE_KEY]
        updates = [_side_update(base, sk, f"{sk}-R1") for sk in SIDE_KEYS]

        _merge_debate_updates(st, updates, state_key=STATE_KEY, side_keys=list(SIDE_KEYS))

        ds = st[STATE_KEY]
        assert len(ds["rounds"]) == 2
        assert set(ds["rounds"][1]) == set(SIDE_KEYS)
        assert ds["count"] == 8
        assert ds["rounds"][0]["bull"] == "R0"  # 历史轮不被覆盖

    def test_latest_speaker_semantics(self):
        """generic 组（has_latest_speaker=False）不写键；True 时写固定序最后成功侧"""
        base = {"rounds": [], "count": 0}
        updates = [_side_update(base, sk, f"{sk}-R0") for sk in SIDE_KEYS]

        st_a = {STATE_KEY: dict(base)}
        _merge_debate_updates(st_a, updates, state_key=STATE_KEY, side_keys=list(SIDE_KEYS))
        assert "latest_speaker" not in st_a[STATE_KEY]

        st_b = {STATE_KEY: dict(base)}
        updates_b = list(updates)
        updates_b[0] = {}  # bull 失败 → 最后成功侧 = quant
        _merge_debate_updates(
            st_b,
            updates_b,
            state_key=STATE_KEY,
            side_keys=list(SIDE_KEYS),
            has_latest_speaker=True,
        )
        assert st_b[STATE_KEY]["latest_speaker"] == "quant-debater"


# ---------------------------------------------------------------------------
# 视图层：generic N 方派生视图
# ---------------------------------------------------------------------------


class TestGenericView:
    def _ds(self) -> dict:
        ds: dict = {"rounds": [], "count": 0}
        append_round(ds, "macro-debater", "宏观首轮。", 4)
        append_round(ds, "bull", "bull 首轮。", 4)
        append_round(ds, "bear", "bear 首轮。", 4)
        append_round(ds, "quant-debater", "quant 首轮。", 4)
        append_round(ds, "macro-debater", "宏观反驳。", 4)
        return ds

    def test_labeled_titles(self):
        view = make_generic_report_content({"macro-debater": "宏观辩手"})
        out = view(self._ds(), "macro-debater")
        assert "## 初始观点：宏观辩手" in out
        assert "宏观首轮。" in out
        assert "## 第 1 轮辩论：宏观辩手 发言" in out
        assert "宏观反驳。" in out
        # 其他侧内容不串入本侧视图
        assert "bull 首轮。" not in out

    def test_registered_fallback_view(self):
        """REPORT_VIEWS 注册的无标签回退版：side_key 原样作标签"""
        out = generic_report_content(self._ds(), "macro-debater")
        assert "## 初始观点：macro-debater" in out

    def test_unknown_side_falls_back_to_key(self):
        view = make_generic_report_content({"macro-debater": "宏观辩手"})
        ds = {"rounds": [{"ghost-side": "幽灵侧观点。"}], "count": 1}
        assert "## 初始观点：ghost-side" in view(ds, "ghost-side")

    def test_empty_state(self):
        view = make_generic_report_content({"macro-debater": "宏观辩手"})
        assert view(None, "macro-debater") == ""
        assert view({"rounds": [], "count": 0}, "macro-debater") == ""


# ---------------------------------------------------------------------------
# 端到端：自定义 4 方工作流真实执行（submit_report 协议驱动）
# ---------------------------------------------------------------------------


@pytest.fixture
def custom_panel_agents(mongodb_available):
    """向 agent_specs 插入 3 个自定义条目（builtin=false），用例后清理并失效缓存。"""
    from app.engine.orchestrator.workflow import store

    now = datetime.now(timezone.utc)
    docs = [
        {
            "_id": "macro-debater",
            "phase": 2,
            "position": 900,
            "builtin": False,
            "deleted": False,
            "created_at": now,
            "updated_at": now,
            "spec": {
                "slug": "macro-debater",
                "name": "宏观辩手",
                "roleDefinition": "你是宏观基本面辩手，从宏观视角论证。",
            },
        },
        {
            "_id": "quant-debater",
            "phase": 2,
            "position": 901,
            "builtin": False,
            "deleted": False,
            "created_at": now,
            "updated_at": now,
            "spec": {
                "slug": "quant-debater",
                "name": "量化辩手",
                "roleDefinition": "你是量化模型辩手，用量化证据论证。",
            },
        },
        {
            "_id": "panel-judge",
            "phase": 2,
            "position": 902,
            "builtin": False,
            "deleted": False,
            "created_at": now,
            "updated_at": now,
            "spec": {
                "slug": "panel-judge",
                "name": "裁决官",
                "roleDefinition": "你是辩论裁决官，综合各方观点给出裁决。",
            },
        },
    ]
    coll = store._db()[store.AGENT_SPECS_COLLECTION]
    coll.delete_many({"_id": {"$in": list(CUSTOM_SLUGS)}})
    coll.insert_many(docs)
    store.invalidate_store_cache()
    yield
    coll.delete_many({"_id": {"$in": list(CUSTOM_SLUGS)}})
    store.invalidate_store_cache()


async def _run_panel(*, parallel: bool = True):
    """编译并执行 4 方辩论工作流，返回 (state, events, client)"""
    plan = _compiled_panel_plan()
    client = _NSideClient()
    sink = _PromptSink()
    state = create_initial_state("000001", "2024-12-31")
    state["_event_sink"] = sink
    deps = PipelineDeps(
        analyst_client=client,
        debate_client=client,
        toolkit=None,
        config={"debate_parallel": parallel},
    )
    await run_compiled(plan, deps, state, event_sink=sink, mcp_tools=[], node_timings={})
    return state, sink.events, client


class TestNSideEndToEnd:
    async def test_four_side_parallel_rounds_complete(self, custom_panel_agents):
        state, events, _ = await _run_panel(parallel=True)

        ds = state[STATE_KEY]
        # 2 轮（rounds=1 → 初始轮 + 1 附加轮），每轮 4 方键集完整
        assert len(ds["rounds"]) == 2
        assert set(ds["rounds"][0]) == set(SIDE_KEYS)
        assert set(ds["rounds"][1]) == set(SIDE_KEYS)
        # count = 4 方 × 2 轮；max_rounds 与实际循环同步
        assert ds["count"] == 8
        assert ds["max_rounds"] == 2
        # 提交正文落 rounds[side]（自定义辩手 side_key = slug）
        assert ds["rounds"][0]["macro-debater"] == SUBMITTED
        assert ds["rounds"][0]["bull"] == SUBMITTED

        # judge 裁决 + terminal 决策字段（workflow.terminal.decision_field）
        assert ds["judge_decision"] == SUBMITTED
        assert state["panel_decision"] == SUBMITTED

        # reports：4 侧派生报告（generic 视图）+ judge 报告键
        assert {
            "bull_researcher",
            "bear_researcher",
            "macro_debater_view",
            "quant_debater_view",
            "panel_judgement",
        } <= set(state["reports"])
        # generic 视图分节标题（标签 = 辩手 node_name）
        assert "## 初始观点：Macro Debater" in state["reports"]["macro_debater_view"]
        assert "## 第 1 轮辩论：Macro Debater 发言" in state["reports"]["macro_debater_view"]

        # 事件序列：每侧 2 轮 agent_start + judge 1 次
        starts = [e for e in events if e["event_type"] == "agent_start"]
        assert {e["agent_key"] for e in starts} == {
            "researcher_bull",
            "researcher_bear",
            "macro_debater",
            "quant_debater",
            "panel_judge",
        }
        for key in ("researcher_bull", "researcher_bear", "macro_debater", "quant_debater"):
            assert len([e for e in starts if e["agent_key"] == key]) == 2
        # 进度走满（completed == total == 9 → percent 100）
        progress = [e for e in events if e["event_type"] == "progress"]
        assert progress and progress[-1]["percent"] == 100
        assert progress[-1]["completed"] == progress[-1]["total"] == 9

    async def test_four_side_serial_path(self, custom_panel_agents):
        """串行回退路径（debate_parallel=False）同样完成 N 方公平轮次"""
        state, _, _ = await _run_panel(parallel=False)

        ds = state[STATE_KEY]
        assert set(ds["rounds"][0]) == set(SIDE_KEYS)
        assert set(ds["rounds"][1]) == set(SIDE_KEYS)
        assert ds["count"] == 8
        assert state["panel_decision"] == SUBMITTED

    async def test_fairness_history_injection(self, custom_panel_agents):
        """Round 1 会话注入完整历史轮（self + 全部对手），不见本轮任何发言外泄。

        通用工厂（macro）的对手标签 = 组内 node_name；内置工厂（bull/bear）的
        内置对手标签 = 被称呼名（看涨/看跌分析师），自定义对手 = 组内 node_name。
        """
        _, _, client = await _run_panel(parallel=True)

        macro_r1 = [s for s in client.sessions if "宏观基本面辩手" in s and "当前阶段：Round 1 辩论" in s]
        assert len(macro_r1) == 1, "macro Round 1 会话应恰有一次"
        prompt = macro_r1[0]
        assert prompt.count("【回顾】") == 4  # self 1 + bull/bear/quant 3
        # 通用工厂对手标签 = 组内辩手 node_name
        assert "Bull Researcher" in prompt
        assert "Bear Researcher" in prompt
        assert "Quant Debater" in prompt
        # Round 0 触发语不串入（本会话是 Round 1）
        assert "当前阶段：Round 0 初始观点陈述" not in prompt

        # 内置工厂的 Round 1 会话：内置对手用被称呼名，自定义对手用组内标签
        builtin_r1 = [s for s in client.sessions if "当前分析阶段：辩论第 1 轮" in s and "【回顾】这是对手（" in s]
        assert builtin_r1, "内置研究员 Round 1 会话（含对手回顾）应存在"
        assert any("（看涨分析师）" in s for s in builtin_r1)  # bear 会话称呼 bull
        assert any("（看跌分析师）" in s for s in builtin_r1)  # bull 会话称呼 bear
        assert any("Macro Debater" in s for s in builtin_r1)  # 自定义对手组内标签

    async def test_judge_sees_all_sides(self, custom_panel_agents):
        """裁决会话注入全部 4 侧累积报告（组拓扑驱动，不限于内置双方）"""
        _, _, client = await _run_panel(parallel=True)

        judge_sessions = [s for s in client.sessions if "辩论裁决官" in s]
        assert len(judge_sessions) == 1
        prompt = judge_sessions[0]
        assert prompt.count("分析报告 ===") == 4  # 4 侧卷宗逐条注入
        for label in ("Bull Researcher", "Bear Researcher", "Macro Debater", "Quant Debater"):
            assert label in prompt
