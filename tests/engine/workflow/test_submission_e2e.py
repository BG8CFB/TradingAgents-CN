"""submit_report 提交协议端到端测试（P3-g，设计文档 §4.6b/§4.7/§4.8）。

与 test_submission.py（协议单元层）互补，本文件锁端到端行为：
- 工具调用型 scripted client 驱动真实 run_pipeline：全节点走结构化提交
  （tool_call/tool_result 事件 + report_ready 携带 structured 标记 +
  trader/final 信号槽取工具参数 + summary 字段取提交值）
- schema 失败有界重试：非法提交 → 工具报错回传（is_error）→ 模型修正重提
- max_turns 未提交 → final_text 降级（fallback_text 标记 + fallback_fields
  回退 + 信号槽不写键，下游回退文本解析）
- debater 白名单：辩手会话工具列表 = 仅 submit_report；提交不即时写黑板，
  report_ready 由辩论组 barrier 合并发射（无 submission 标记）

驱动方式（项目规则：全真 I/O、禁 mock 库）：
- _SubmitClient 系列 = BaseLLMClient 真实子类，按「messages 末尾是否为
  工具结果块」驱动状态机（首轮提交 / 收到结果后收尾），不感知节点身份
"""

from app.engine.orchestrator.invoker import run_node_turn
from app.engine.orchestrator.pipeline import PipelineDeps, run_pipeline
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

# 超集合法提交参数：覆盖全部 node_type 的必填字段（analyst/debater/judge
# 忽略额外字段，trader/terminal 取 action，summarizer 取 7 结构化字段）
SUPERSET_INPUT = {
    "content": "提交的正文。",
    "action": "买入",
    "target_price": 12.5,
    "confidence": 0.8,
    "risk_score": 0.3,
    "reasoning": "趋势向好",
    "key_indicators": {"entry_price": "10", "target_price": "13"},
    "model_confidence": 88,
    "risk_assessment": {"level": "Low", "score": 2.0, "description": "低风险"},
    "analysis_summary": "摘要",
    "investment_recommendation": "建议买入",
    "analysis_reference": ["依据一"],
    "final_signal": "Buy",
}

# 最小场景（与 golden g4 一致）：市场技术 + 短线资金，辩论/风控全开
_G4_CONFIG = {
    "phase2_enabled": True,
    "phase3_enabled": True,
    "phase2_debate_rounds": 1,
    "phase3_debate_rounds": 1,
}
_G4_SELECTED = ["market-analyst", "short-term-capital-analyst"]

# 即时写黑板（report_key 非空）的节点 agent_key：analyst + judge（裁决三落点
# 之一 research_team_decision）+ risk_manager；trader/summary 不带 report_key，
# debater 由辩论组 barrier 管理
_INSTANT_COMMIT_AGENTS = {"market", "short_term_capital", "research_manager", "risk_manager"}


def _last_is_tool_result(messages) -> bool:
    """会话状态机判据：末条 USER 消息是否为工具结果块（= 工具已执行，应收尾）"""
    if not messages:
        return False
    last = messages[-1]
    return last.role == Role.USER and any(
        isinstance(b, ToolResultBlock) for b in last.blocks()
    )


class _SubmitClient(BaseLLMClient):
    """首轮提交超集合法参数、收到工具结果后返回收尾文本（真实子类）。

    calls 记录每次会话首调时的工具名单（白名单断言数据源）
    """

    protocol = "test"
    model = "test-submit-model"

    def __init__(self, submitted_content: str = "提交的正文。"):
        self.calls: list = []
        self._content = submitted_content

    def _first_turn_input(self) -> dict:
        return {**SUPERSET_INPUT, "content": self._content}

    async def chat_stream(self, messages, *, system=None, tools=None, **kwargs):
        tool_names = [t.name for t in (tools or [])]
        if not _last_is_tool_result(messages):
            self.calls.append({"tools": tool_names})
            resp = self._tool_resp(self._first_turn_input())
        else:
            resp = self._text_resp("已提交，收尾。")
        yield StreamEvent("message", response=resp)

    async def chat(self, messages, **kwargs) -> ChatResponse:
        if _last_is_tool_result(messages):
            return self._text_resp("已提交，收尾。")
        return self._tool_resp(self._first_turn_input())

    async def count_tokens(self, messages) -> int:
        return 16

    def _tool_resp(self, input: dict) -> ChatResponse:
        return ChatResponse(
            message=Message(
                role=Role.ASSISTANT,
                content=[
                    TextBlock(text="报告如下，现提交。"),
                    ToolUseBlock(id="toolu_submit_1", name="submit_report", input=input),
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


class _RetryClient(_SubmitClient):
    """首次提交非法枚举（action=梭哈），收到错误结果后修正重提"""

    def __init__(self):
        super().__init__()
        self._fixed = False

    def _first_turn_input(self) -> dict:
        if not self._fixed:
            return {**SUPERSET_INPUT, "action": "梭哈"}
        return SUPERSET_INPUT

    async def chat_stream(self, messages, *, system=None, tools=None, **kwargs):
        tool_names = [t.name for t in (tools or [])]
        if not _last_is_tool_result(messages):
            self.calls.append({"tools": tool_names})
            resp = self._tool_resp(self._first_turn_input())
        else:
            # 收到的工具结果是否为错误（校验失败回传）→ 修正标记后重提；
            # 成功结果（或已修正后再失败）→ 收尾文本（max_turns=2 下自然耗尽）
            last_error = any(
                getattr(b, "is_error", False) for b in messages[-1].blocks()
            )
            if last_error and not self._fixed:
                self._fixed = True
                resp = self._tool_resp(SUPERSET_INPUT)
            else:
                resp = self._text_resp("已提交，收尾。")
        yield StreamEvent("message", response=resp)


class _AlwaysInvalidClient(_SubmitClient):
    """每轮都提交非法参数（连续校验失败 → max_turns 耗尽 → 降级）"""

    def _first_turn_input(self) -> dict:
        return {**SUPERSET_INPUT, "action": "梭哈"}

    async def chat_stream(self, messages, *, system=None, tools=None, **kwargs):
        if not _last_is_tool_result(messages):
            self.calls.append({"tools": [t.name for t in (tools or [])]})
            resp = self._tool_resp(self._first_turn_input())
        else:
            resp = self._tool_resp(self._first_turn_input())  # 重试仍非法
        yield StreamEvent("message", response=resp)


class _PlainTextClient(BaseLLMClient):
    """纯文本回复（永不调工具 → final_text 降级路径，golden 同款驱动）"""

    protocol = "test"
    model = "test-text-model"

    def __init__(self, text: str):
        self._text = text

    async def chat_stream(self, messages, **kwargs):
        yield StreamEvent("message", response=self._resp())

    async def chat(self, messages, **kwargs) -> ChatResponse:
        return self._resp()

    async def count_tokens(self, messages) -> int:
        return 16

    def _resp(self) -> ChatResponse:
        return ChatResponse(
            message=Message(role=Role.ASSISTANT, content=[TextBlock(text=self._text)]),
            stop_reason=StopReason.END_TURN,
            usage=Usage(input_tokens=10, output_tokens=5),
            model=self.model,
        )


class _ListSink:
    """事件捕获 sink（与 pipeline 消费的 EventSink 接口兼容）"""

    def __init__(self):
        self.events: list = []

    async def emit(self, event_type: str, **fields):
        self.events.append({"event_type": event_type, **fields})

    def mark_running(self, key: str):
        pass

    def mark_completed(self, key: str):
        pass


async def _run_with(client_analyst, client_debate):
    """g4 最小场景跑 run_pipeline，返回 (state, events)"""
    sink = _ListSink()
    deps = PipelineDeps(
        analyst_client=client_analyst,
        debate_client=client_debate,
        toolkit=None,
        config=dict(_G4_CONFIG),
    )
    state = await run_pipeline(
        deps,
        "000001",
        "2024-12-31",
        selected_analysts=list(_G4_SELECTED),
        event_sink=sink,
    )
    return state, sink.events


class TestStructuredSubmissionPipeline:
    """全节点结构化提交的端到端行为（_SubmitClient 驱动真实流水线）"""

    async def test_tool_call_events_present(self):
        _, events = await _run_with(_SubmitClient(), _SubmitClient())

        submits = [
            e for e in events
            if e["event_type"] == "tool_call" and e.get("tool") == "submit_report"
        ]
        results = [
            e for e in events
            if e["event_type"] == "tool_result" and e.get("tool") == "submit_report"
        ]
        # 每个节点至少一次成功提交（analyst 2 + 辩手/裁决/trader/风控辩论/summary）
        assert len(submits) >= 10
        assert {e["agent_key"] for e in submits} >= {
            "market", "short_term_capital",
            "researcher_bull", "researcher_bear", "research_manager", "trader",
            "risk_debater_risky", "risk_debater_safe", "risk_debater_neutral",
            "risk_manager", "summary",
        }
        # 全部提交成功（超集参数对任何 node_type 均合法）
        assert all(not e.get("is_error") for e in results)
        assert len(results) == len(submits)

    async def test_report_ready_submission_markers(self):
        _, events = await _run_with(_SubmitClient(), _SubmitClient())
        ready = [e for e in events if e["event_type"] == "report_ready"]

        structured = {e["agent_key"] for e in ready if e.get("submission") == "structured"}
        # 即时发射（工具提交路径）= report_key 非空的节点：analyst + risk_manager
        assert structured == _INSTANT_COMMIT_AGENTS

        # debater（辩手）的 report_ready 无 submission 标记 = 辩论组 barrier
        # 合并路径发射，非工具即时提交
        debater_ready = {e["agent_key"] for e in ready if e["agent_key"].startswith(("researcher_", "risk_debater_"))}
        assert {"researcher_bull", "researcher_bear", "risk_debater_risky", "risk_debater_safe", "risk_debater_neutral"} <= debater_ready
        for e in ready:
            if e["agent_key"] in debater_ready:
                assert "submission" not in e

        # 非辩手节点同一 (agent_key, report_key) 不双发（即时提交后内容不变，
        # merge diff 自然跳过）；辩手报告为累积视图（rounds 逐轮派生），每轮
        # 发言刷新一次 report_ready 属既定语义（前端逐轮更新辩手报告）
        non_debater: dict = {}
        debater_events: dict = {}
        for e in ready:
            key = (e["agent_key"], e["report_key"])
            if e["agent_key"].startswith(("researcher_", "risk_debater_")):
                debater_events.setdefault(key, []).append(e["content"])
            else:
                assert key not in non_debater, f"report_ready 双发: {key}"
                non_debater[key] = e
        for key, contents in debater_events.items():
            assert all(
                len(later) >= len(earlier) for earlier, later in zip(contents, contents[1:])
            ), f"辩手累积视图应单调增长: {key}: {[len(c) for c in contents]}"

    async def test_signal_slots_from_tool_params(self):
        """§4.8 优先级翻转的一手来源：结构化决策字段写入信号槽"""
        state, _ = await _run_with(_SubmitClient(), _SubmitClient())

        assert state["trader_decision_signal"]["action"] == "买入"
        assert state["trader_decision_signal"]["target_price"] == 12.5
        assert state["final_decision_signal"]["action"] == "买入"
        assert state["final_decision_signal"]["reasoning"] == "趋势向好"

    async def test_summary_fields_from_submission(self):
        """structured_summary 取工具提交的结构化字段（非正文 JSON 解析）"""
        state, _ = await _run_with(_SubmitClient(), _SubmitClient())
        summary = state["structured_summary"]

        assert summary["model_confidence"] == 88
        assert summary["final_signal"] == "Buy"
        assert summary["key_indicators"] == SUPERSET_INPUT["key_indicators"]
        assert summary["analysis_reference"] == ["依据一"]

    async def test_debate_rounds_use_submitted_content(self):
        """辩手提交内容落 rounds[side]（白名单提交协议的落点）"""
        state, _ = await _run_with(_SubmitClient(), _SubmitClient("辩手论点正文。"))

        inv_rounds = state["investment_debate_state"]["rounds"]
        assert inv_rounds[0]["bull"] == "辩手论点正文。"
        assert inv_rounds[0]["bear"] == "辩手论点正文。"
        risk_rounds = state["risk_debate_state"]["rounds"]
        assert risk_rounds[0]["risky"] == "辩手论点正文。"


class TestSchemaRetryBounded:
    """schema 校验失败 → 工具报错回传模型 → 有界重试（计入 max_turns）"""

    async def test_invalid_then_valid_resubmits(self):
        client = _RetryClient()
        sink = _ListSink()
        submission = await run_node_turn(
            client, [], "请提交",
            system="s", node_type="trader",
            report_key="trader_plan_view", state={}, event_sink=sink,
            agent_key="trader", phase="trader",
        )

        assert submission.source == "structured"
        assert submission.fields["action"] == "买入"

        results = [e for e in sink.events if e["event_type"] == "tool_result"]
        assert len(results) == 2
        # 第一次：非法枚举被拒（错误信息面向模型，指明 action 合法值）
        assert results[0]["is_error"] is True
        assert "action" in results[0]["output"]
        # 第二次：修正后成功
        assert results[1]["is_error"] is False

    async def test_repeated_invalid_falls_back(self):
        """连续两次非法提交 → max_turns 耗尽 box 空 → fallback_text 降级"""
        client = _AlwaysInvalidClient()
        submission = await run_node_turn(
            client, [], "请提交",
            system="s", node_type="trader",
            fallback_fields={"action": "持有"},
        )

        assert submission.source == "fallback_text"
        assert submission.fields == {"action": "持有"}
        # 纯工具轮无正文 → 降级 content 为空串（调用方按 H-2 占位降级）
        assert submission.content == ""


class TestFallbackPipeline:
    """模型未调工具（纯文本）→ fallback_text 降级的端到端行为"""

    async def test_fallback_fields_used_at_protocol(self):
        submission = await run_node_turn(
            _PlainTextClient("文本计划。"), [], "请提交",
            system="s", node_type="trader",
            fallback_fields={"action": "持有"},
        )
        assert submission.source == "fallback_text"
        assert submission.content == "文本计划。"
        assert submission.fields == {"action": "持有"}

    async def test_no_signal_keys_when_fallback(self):
        """fallback 提交不写信号槽键 → 下游回退 SignalProcessor 文本解析"""
        state, events = await _run_with(
            _PlainTextClient("分析师报告。"), _PlainTextClient("阶段输出：综合判断为积极。"),
        )
        assert "trader_decision_signal" not in state
        assert "final_decision_signal" not in state
        # 全部 report_ready 无 structured 标记（merge 路径发射）
        ready = [e for e in events if e["event_type"] == "report_ready"]
        assert ready and all("submission" not in e for e in ready)


class TestDebaterWhitelist:
    """debater 工具白名单 = 仅 submit_report（§4.2/§4.6b）"""

    async def test_debate_sessions_only_submit_tool(self):
        """辩手类会话（Stage 2-4 全部节点）的工具列表恰为 [submit_report]"""
        analyst_client = _SubmitClient()
        debate_client = _SubmitClient()
        await _run_with(analyst_client, debate_client)

        # debate_client 服务 Stage 2-4 全部节点：每次首调 tools 恰为提交工具
        assert debate_client.calls, "辩手会话未被调用"
        for call in debate_client.calls:
            assert call["tools"] == ["submit_report"], (
                f"白名单违规: {call['tools']}"
            )

        # analyst 会话 = 数据工具 + submit_report（提交入口仍唯一）
        assert analyst_client.calls
        for call in analyst_client.calls:
            assert call["tools"].count("submit_report") == 1

    async def test_debater_no_instant_blackboard_write(self):
        """协议单元：report_key 空 → 不写黑板不发事件（rounds 由辩论组管理）"""
        from app.engine.orchestrator.workflow.submission import SubmissionBox, make_submit_report_tool

        box = SubmissionBox()
        state: dict = {}
        sink = _ListSink()
        tool = make_submit_report_tool(
            box, node_type="debater", state=state, event_sink=sink,
            agent_key="researcher_bull", phase="research",
        )
        await tool.handler(content="辩手发言。")

        assert state.get("reports", {}) == {}
        assert sink.events == []
        assert box.value.content == "辩手发言。"
