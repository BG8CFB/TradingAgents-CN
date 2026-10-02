"""golden 等价测试：默认工作流编译执行 vs 现有 run_pipeline 的行为锁定。

用途（P2 双重验收）：
1. 存储迁移（YAML → DB）前后：事件序列 / state 形状 / reports 键集合逐项相等
2. 编排重构（executor 遍历 plan）前后：同上

驱动方式（项目规则：全真 I/O、禁 mock 库）：
- _FixedReplyClient = BaseLLMClient 真实子类，固定单轮文本回复（确定性，无 LLM 凭据可跑）
- _ListSink = 事件捕获器（与 EventSink 的 emit/mark_* 接口兼容，只断言 emit 的真实事件）

基线重生成：GOLDEN_REGENERATE=1 python -m pytest tests/engine/workflow/test_golden_equivalence.py
（重生成后仍执行断言 = 首遍自校验；基线文件必须随代码 review 提交）

断言粒度五层：
① 阶段首现序（agent_start 的 phase 去重保序）——跨阶段强序
② 每 agent 事件序列（单 agent 维度强序，规避并行交错）
③ agent_start 的 (phase, agent_key) 多重集合——覆盖完整性
④ state 形状：顶层键集 / debate 数值与轮次 side 集 / 决策字段非空性
⑤ reports 键集合 + node_timings 键集合（排序比较，规避并行完成序）
"""

import json
import os
from pathlib import Path
from typing import Any, Dict, List, Tuple

import pytest

from app.engine.orchestrator.pipeline import PipelineDeps, run_pipeline
from app.llm.core.base import BaseLLMClient, StreamEvent
from app.llm.core.types import (
    ChatResponse,
    Message,
    Role,
    StopReason,
    TextBlock,
    Usage,
)

GOLDEN_DIR = Path(__file__).resolve().parent / "golden"
BASELINE_PATH = GOLDEN_DIR / "baseline.json"

# 默认全家桶（phase1 YAML default_selected=true 的 5 个；市场技术/短线资金为硬依赖）
DEFAULT_BASKET = [
    "market-analyst",
    "financial-news-analyst",
    "social-media-analyst",
    "china-market-analyst",
    "short-term-capital-analyst",
]

SCENARIOS: Dict[str, Dict[str, Any]] = {
    "g1_full": dict(
        config={"phase2_enabled": True, "phase3_enabled": True, "phase2_debate_rounds": 1, "phase3_debate_rounds": 1},
        selected=DEFAULT_BASKET,
    ),
    "g2_research_only": dict(
        config={"phase2_enabled": True, "phase3_enabled": False, "phase2_debate_rounds": 1},
        selected=DEFAULT_BASKET,
    ),
    "g3_risk_only": dict(
        config={"phase2_enabled": False, "phase3_enabled": True, "phase3_debate_rounds": 1},
        selected=DEFAULT_BASKET,
    ),
    # 合法最小子集：市场技术 + 短线资金（L263 required 槽——单裁 market 会被编译期拒绝，
    # 拒绝路径断言见 TestRequiredInputsFailFast）
    "g4_subset_minimal": dict(
        config={"phase2_enabled": True, "phase3_enabled": True, "phase2_debate_rounds": 1, "phase3_debate_rounds": 1},
        selected=["market-analyst", "short-term-capital-analyst"],
    ),
    # submit_report 提交协议场景（P3 行为变更声明 §4.6b）：会调工具的 scripted
    # client 驱动，事件序列含 tool_call/tool_result；专项行为断言见
    # test_submission_e2e.py，本场景锁「协议接入后事件序列形状」供后续重构对照
    "g5_submit_protocol": dict(
        config={"phase2_enabled": True, "phase3_enabled": True, "phase2_debate_rounds": 1, "phase3_debate_rounds": 1},
        selected=["market-analyst", "short-term-capital-analyst"],
        client="submit",
    ),
}

# 内部标记（非 emit 事件），capture 时排除
_MARK_EVENTS = {"mark_running", "mark_completed"}


class _FixedReplyClient(BaseLLMClient):
    """每次调用返回固定单轮文本回复（确定性驱动；真实子类，非 mock 库）"""

    protocol = "test"
    model = "test-model"

    def __init__(self, text: str):
        self._text = text

    async def chat(self, messages, **kwargs) -> ChatResponse:
        return self._resp()

    async def chat_stream(self, messages, **kwargs):
        yield StreamEvent("message", response=self._resp())

    async def count_tokens(self, messages) -> int:
        return 16

    def _resp(self) -> ChatResponse:
        return ChatResponse(
            message=Message(role=Role.ASSISTANT, content=[TextBlock(text=self._text)]),
            stop_reason=StopReason.END_TURN,
            usage=Usage(input_tokens=10, output_tokens=5),
            model="test-model",
        )


class _ListSink:
    """事件捕获 sink（与 pipeline 消费的 EventSink 接口兼容）"""

    def __init__(self):
        self.events: List[Dict[str, Any]] = []

    async def emit(self, event_type: str, **fields):
        self.events.append({"event_type": event_type, **fields})

    def mark_running(self, key: str):
        self.events.append({"event_type": "mark_running", "agent_key": key})

    def mark_completed(self, key: str):
        self.events.append({"event_type": "mark_completed", "agent_key": key})


async def _run_scenario(scenario: Dict[str, Any]) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    """跑一个场景，返回 (最终 state, 捕获事件)。

    client 键选驱动：缺省纯文本（fallback_text 路径）；"submit" 用会调
    submit_report 的 scripted client（structured 提交路径）
    """
    if scenario.get("client") == "submit":
        from tests.engine.workflow.test_submission_e2e import _SubmitClient

        analyst_client = _SubmitClient("分析师报告：均线多头排列。")
        debate_client = _SubmitClient("阶段输出：综合判断为积极。")
    else:
        analyst_client = _FixedReplyClient("分析师报告：均线多头排列。")
        debate_client = _FixedReplyClient("阶段输出：综合判断为积极。")
    sink = _ListSink()
    deps = PipelineDeps(
        analyst_client=analyst_client,
        debate_client=debate_client,
        toolkit=None,
        config=dict(scenario["config"]),
    )
    state = await run_pipeline(
        deps,
        "000001",
        "2024-12-31",
        selected_analysts=list(scenario["selected"]),
        event_sink=sink,
    )
    return state, sink.events


def _capture_baseline(state: Dict[str, Any], events: List[Dict[str, Any]]) -> Dict[str, Any]:
    """从 (state, events) 提取规范化基线（并行无关的确定性形状）"""
    seq = [(e.get("event_type"), e.get("agent_key", "")) for e in events if e.get("event_type") not in _MARK_EVENTS]

    # ① 阶段首现序：agent_start 的 phase 去重保序
    phase_first_seen: List[str] = []
    for e in events:
        if e.get("event_type") == "agent_start":
            ph = e.get("phase", "")
            if ph not in phase_first_seen:
                phase_first_seen.append(ph)

    # ② 每 agent 事件序列（单 agent 维度强序）
    agent_seqs: Dict[str, List[str]] = {}
    for et, ak in seq:
        if ak:
            agent_seqs.setdefault(ak, []).append(et)

    # ③ agent_start 的 (phase, agent_key) 多重集合
    # 注意必须用 list 而非 tuple：tuple 经 JSON roundtrip 变 list，导致录制值与重载值永不相等
    agent_starts = sorted(
        [e.get("phase", ""), e.get("agent_key", "")] for e in events if e.get("event_type") == "agent_start"
    )

    def _debate_shape(key: str) -> Dict[str, Any]:
        ds = state.get(key) or {}
        rounds = ds.get("rounds") or []
        return {
            "count": ds.get("count"),
            "max_rounds": ds.get("max_rounds"),
            "current_round_index": ds.get("current_round_index"),
            "latest_speaker": ds.get("latest_speaker", ""),
            "judge_decision_nonempty": bool(ds.get("judge_decision")),
            "rounds_sides": [sorted(r.keys()) if isinstance(r, dict) else [] for r in rounds],
        }

    return {
        "phase_first_seen": phase_first_seen,
        "agent_event_seqs": {k: agent_seqs[k] for k in sorted(agent_seqs)},
        "agent_starts": agent_starts,
        # _plan_snapshot 是 2026-09 编排重构新增的执行计划快照键（独立断言，见用例内），
        # 剥离后与旧基线键集精确对比——保住「重写前后 state 形状等价」的对照强度
        "state_top_keys": sorted(k for k in state.keys() if k != "_plan_snapshot"),
        "reports_keys": sorted((state.get("reports") or {}).keys()),
        "node_timings_keys": sorted((state.get("node_timings") or {}).keys()),
        "investment_debate": _debate_shape("investment_debate_state"),
        "risk_debate": _debate_shape("risk_debate_state"),
        "decision": {
            "trader_investment_plan_nonempty": bool(state.get("trader_investment_plan")),
            "final_trade_decision_nonempty": bool(state.get("final_trade_decision")),
            "investment_plan_nonempty": bool(state.get("investment_plan")),
            "structured_summary_nonempty": bool(state.get("structured_summary")),
        },
    }


async def _collect_all() -> Dict[str, Any]:
    """跑全部场景，收集基线"""
    baseline: Dict[str, Any] = {}
    for name, scenario in SCENARIOS.items():
        state, events = await _run_scenario(scenario)
        baseline[name] = _capture_baseline(state, events)
    return baseline


def _load_baseline() -> Dict[str, Any]:
    if not BASELINE_PATH.is_file():
        pytest.fail(
            f"golden 基线不存在: {BASELINE_PATH}\n"
            "重生成：GOLDEN_REGENERATE=1 python -m pytest tests/engine/workflow/test_golden_equivalence.py"
        )
    return json.loads(BASELINE_PATH.read_text(encoding="utf-8"))


class TestGoldenEquivalence:
    @pytest.fixture(autouse=True)
    async def _regenerate_once(self):
        """regenerate 模式：首个用例前重写基线（每进程只执行一次）"""
        should_regenerate = os.environ.get("GOLDEN_REGENERATE") == "1" and not getattr(
            TestGoldenEquivalence, "_regenerated", False
        )
        if should_regenerate:
            baseline = await _collect_all()
            GOLDEN_DIR.mkdir(parents=True, exist_ok=True)
            BASELINE_PATH.write_text(
                json.dumps(baseline, ensure_ascii=True, indent=1, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            TestGoldenEquivalence._regenerated = True
        yield

    @pytest.mark.parametrize("scenario_name", list(SCENARIOS))
    async def test_scenario_matches_baseline(self, scenario_name):
        expected = _load_baseline()[scenario_name]

        state, events = await _run_scenario(SCENARIOS[scenario_name])
        actual = _capture_baseline(state, events)

        # 五层断言，逐层给出可读 diff
        assert actual["phase_first_seen"] == expected["phase_first_seen"], (
            f"[{scenario_name}] 阶段首现序漂移:\n"
            f"  actual:   {actual['phase_first_seen']}\n  expected: {expected['phase_first_seen']}"
        )
        seq_diff = {
            k: (actual["agent_event_seqs"][k], expected["agent_event_seqs"][k])
            for k in set(actual["agent_event_seqs"]) & set(expected["agent_event_seqs"])
            if actual["agent_event_seqs"][k] != expected["agent_event_seqs"][k]
        }
        assert actual["agent_event_seqs"] == expected["agent_event_seqs"], (
            f"[{scenario_name}] agent 事件序列漂移:\n"
            f"  only-actual keys:   {set(actual['agent_event_seqs']) - set(expected['agent_event_seqs'])}\n"
            f"  only-expected keys: {set(expected['agent_event_seqs']) - set(actual['agent_event_seqs'])}\n"
            f"  seq diff: {seq_diff}"
        )
        assert actual["agent_starts"] == expected["agent_starts"], f"[{scenario_name}] agent_start 集合漂移"
        assert actual["state_top_keys"] == expected["state_top_keys"], (
            f"[{scenario_name}] state 顶层键集漂移:\n"
            f"  only-actual:   {set(actual['state_top_keys']) - set(expected['state_top_keys'])}\n"
            f"  only-expected: {set(expected['state_top_keys']) - set(actual['state_top_keys'])}"
        )
        assert actual["reports_keys"] == expected["reports_keys"], (
            f"[{scenario_name}] reports 键集漂移:\n"
            f"  only-actual:   {set(actual['reports_keys']) - set(expected['reports_keys'])}\n"
            f"  only-expected: {set(expected['reports_keys']) - set(actual['reports_keys'])}"
        )
        assert actual["node_timings_keys"] == expected["node_timings_keys"], f"[{scenario_name}] node_timings 键集漂移"
        assert actual["investment_debate"] == expected["investment_debate"], (
            f"[{scenario_name}] 研究辩论形状漂移:\n  actual: {actual['investment_debate']}\n  expected: {expected['investment_debate']}"
        )
        assert actual["risk_debate"] == expected["risk_debate"], (
            f"[{scenario_name}] 风险辩论形状漂移:\n  actual: {actual['risk_debate']}\n  expected: {expected['risk_debate']}"
        )
        assert actual["decision"] == expected["decision"], (
            f"[{scenario_name}] 决策字段漂移:\n  actual: {actual['decision']}\n  expected: {expected['decision']}"
        )

        # 执行计划快照（2026-09 编排重构新增契约，独立于旧基线）：导出 state 必含
        # 冻结的编译元数据（spec_hash + params + compiled_at），在跑任务不受编辑影响
        snap = state.get("_plan_snapshot")
        assert isinstance(snap, dict) and snap.get("workflow_slug") == "default-4stage", (
            f"[{scenario_name}] 缺少执行计划快照: {snap!r}"
        )
        assert str(snap.get("spec_hash", "")).startswith("sha256:"), f"[{scenario_name}] 快照缺 spec_hash"
        assert "params" in snap and "compiled_at" in snap, f"[{scenario_name}] 快照字段不全: {sorted(snap)}"


class TestRequiredInputsFailFast:
    """L263 行为变更：裁掉 required 槽来源（市场技术/短线资金）→ 编译期拒绝任务。

    此前裁掉会静默跑出劣质报告；P3 起在 run_pipeline 编译点 fail-fast。
    """

    async def test_cut_required_analyst_rejected(self):
        from app.engine.orchestrator.workflow.compiler import CompileError

        deps = PipelineDeps(
            analyst_client=_FixedReplyClient("分析师报告。"),
            debate_client=_FixedReplyClient("阶段输出。"),
            toolkit=None,
            config={"phase2_enabled": True, "phase3_enabled": True},
        )
        with pytest.raises(CompileError) as exc_info:
            await run_pipeline(
                deps,
                "000001",
                "2024-12-31",
                selected_analysts=["market-analyst"],  # 缺短线资金
                event_sink=_ListSink(),
            )
        message = str(exc_info.value)
        assert "short_term_capital_report" in message
        assert "必需输入" in message

    async def test_legal_minimal_subset_accepted(self):
        """市场技术 + 短线资金 = 合法最小子集，正常跑完（不抛 CompileError）"""
        state, _ = await _run_scenario(SCENARIOS["g4_subset_minimal"])
        assert state.get("trader_investment_plan")
