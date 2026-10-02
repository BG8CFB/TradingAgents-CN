"""submit_report 提交协议测试（P3-c，设计文档 §4.6b/§4.7）。

全真对象（真实 ToolDef / 真实 dict state / 捕获 sink），无 mock 库：
- type × schema：参数 schema 形状（content 必填 + type 附加字段）
- 校验规范化：action/final_signal 别名归一、数值宽容转换与裁剪、缺失报错可读
- 工具 handler：合法提交写 box + 黑板 + report_ready（submission 标记）；
  重复提交拒绝；非法提交 SubmissionError（模型有界重试）
- debater 例外：report_key 空 → 不写黑板不发事件
- 降级：finalize 未提交 → final_text + fallback_fields + fallback_text 标记
"""

import pytest

from app.engine.orchestrator.workflow.submission import (
    SUBMISSION_FALLBACK,
    SUBMISSION_STRUCTURED,
    SubmissionBox,
    SubmissionError,
    build_params_schema,
    build_tool_description,
    commit_submission,
    finalize_submission,
    make_submit_report_tool,
    validate_submission,
)


class _CaptureSink:
    """事件捕获 sink（与 pipeline 消费的 EventSink emit 接口兼容）"""

    def __init__(self):
        self.events: list = []

    async def emit(self, event_type: str, **fields):
        self.events.append({"event_type": event_type, **fields})


def _run_handler(tool, **input):
    """同步驱动 async handler（工具执行器等价路径）"""
    import asyncio

    return asyncio.run(tool.handler(**input))


class TestSchema:
    def test_content_required_for_all_types(self):
        for node_type in ("analyst", "debater", "judge", "trader", "summarizer", "terminal"):
            schema = build_params_schema(node_type)
            assert schema["type"] == "object"
            assert "content" in schema["properties"]
            assert "content" in schema["required"]

    def test_analyst_debater_judge_content_only(self):
        """纯文本类型：无附加结构化字段（judge 落点映射见模块 docstring）"""
        for node_type in ("analyst", "debater", "judge"):
            schema = build_params_schema(node_type)
            assert set(schema["properties"]) == {"content"}
            assert schema["required"] == ["content"]

    def test_trader_decision_fields(self):
        schema = build_params_schema("trader")
        assert "action" in schema["required"]
        assert schema["properties"]["action"]["enum"] == ["买入", "持有", "卖出"]
        assert "target_price" in schema["properties"]

    def test_summarizer_eight_params(self):
        """summarizer = content + 7 结构化字段（原 structured_summary schema 前置）"""
        schema = build_params_schema("summarizer")
        props = set(schema["properties"])
        assert props == {
            "content", "key_indicators", "model_confidence", "risk_assessment",
            "analysis_summary", "investment_recommendation", "analysis_reference",
            "final_signal",
        }
        assert schema["properties"]["final_signal"]["enum"] == ["Buy", "Hold", "Sell"]

    def test_unknown_type_rejected(self):
        with pytest.raises(SubmissionError):
            build_params_schema("oracle")

    def test_description_mentions_single_entry(self):
        desc = build_tool_description("trader")
        assert "唯一提交入口" in desc
        assert "action" in desc


class TestValidation:
    def test_content_missing_rejected(self):
        with pytest.raises(SubmissionError, match="content"):
            validate_submission("analyst", "", {})
        with pytest.raises(SubmissionError, match="content"):
            validate_submission("analyst", None, {})

    def test_text_types_ignore_extra_fields(self):
        assert validate_submission("analyst", "正文", {"action": "买入"}) == {}

    def test_action_alias_normalized(self):
        fields = validate_submission("trader", "计划", {"action": "Buy"})
        assert fields["action"] == "买入"
        fields = validate_submission("terminal", "裁决", {"action": "观望"})
        assert fields["action"] == "持有"

    def test_action_missing_rejected(self):
        with pytest.raises(SubmissionError, match="action"):
            validate_submission("trader", "计划", {})

    def test_action_invalid_rejected(self):
        with pytest.raises(SubmissionError, match="action"):
            validate_submission("trader", "计划", {"action": "梭哈"})

    def test_numeric_coercion_and_clamp(self):
        fields = validate_submission(
            "trader", "计划",
            {"action": "买入", "target_price": "12.5", "confidence": 1.8, "risk_score": -0.2},
        )
        assert fields["target_price"] == 12.5
        assert fields["confidence"] == 1.0
        assert fields["risk_score"] == 0.0

    def test_target_price_malformed_rejected(self):
        with pytest.raises(SubmissionError, match="target_price"):
            validate_submission("trader", "计划", {"action": "买入", "target_price": "约12元"})

    def test_summarizer_missing_fields_listed(self):
        with pytest.raises(SubmissionError, match="model_confidence"):
            validate_submission(
                "summarizer", "总结",
                {"key_indicators": {}, "risk_assessment": {}, "analysis_summary": "x",
                 "investment_recommendation": "y", "final_signal": "Hold"},
            )

    def test_summarizer_signal_normalized(self):
        fields = validate_submission(
            "summarizer", "总结",
            {"key_indicators": {"entry_price": "10"}, "model_confidence": 200,
             "risk_assessment": {"level": "Low"}, "analysis_summary": "s",
             "investment_recommendation": "r", "final_signal": "买入",
             "analysis_reference": ["a", 1]},
        )
        assert fields["final_signal"] == "Buy"
        assert fields["model_confidence"] == 100  # 裁剪到 0-100
        assert fields["analysis_reference"] == ["a", "1"]

    def test_summarizer_object_type_enforced(self):
        raw = {"key_indicators": "点位", "model_confidence": 50, "risk_assessment": {},
               "analysis_summary": "s", "investment_recommendation": "r", "final_signal": "Hold"}
        with pytest.raises(SubmissionError, match="key_indicators"):
            validate_submission("summarizer", "总结", raw)


class TestToolHandler:
    async def test_valid_submission_writes_box_and_board(self):
        box = SubmissionBox()
        state = {"reports": {}}
        sink = _CaptureSink()
        tool = make_submit_report_tool(
            box, node_type="trader", report_key="trader_plan_view",
            state=state, event_sink=sink, agent_key="trader", phase="trader",
        )
        out = await tool.handler(content="买入计划正文。", action="买入", target_price=12.5)

        assert "已收到报告提交" in out
        assert box.value is not None
        assert box.value.source == SUBMISSION_STRUCTURED
        assert box.value.content == "买入计划正文。"
        assert box.value.fields["action"] == "买入"
        assert state["reports"]["trader_plan_view"] == "买入计划正文。"
        # report_ready 即时发射，携带来源标记与标题
        assert len(sink.events) == 1
        event = sink.events[0]
        assert event["event_type"] == "report_ready"
        assert event["submission"] == SUBMISSION_STRUCTURED
        assert event["report_key"] == "trader_plan_view"
        assert event["title"]  # registry 标题解析有值

    async def test_duplicate_submission_rejected(self):
        box = SubmissionBox()
        tool = make_submit_report_tool(box, node_type="analyst")
        await tool.handler(content="报告一")
        with pytest.raises(SubmissionError, match="重复提交"):
            await tool.handler(content="报告二")
        assert box.value.content == "报告一"

    async def test_invalid_submission_not_captured(self):
        """校验失败的提交不落 box（模型修正后重试）"""
        box = SubmissionBox()
        tool = make_submit_report_tool(box, node_type="trader")
        with pytest.raises(SubmissionError):
            await tool.handler(content="计划", action="梭哈")
        assert box.value is None

    async def test_debater_no_blackboard_write(self):
        """debater 例外：report_key 空 → 不写黑板不发事件（rounds 由辩论组管理）"""
        box = SubmissionBox()
        state = {"reports": {}}
        sink = _CaptureSink()
        tool = make_submit_report_tool(
            box, node_type="debater", state=state, event_sink=sink,
        )
        await tool.handler(content="本轮发言。")
        assert box.value.content == "本轮发言。"
        assert state["reports"] == {}
        assert sink.events == []

    def test_unknown_type_rejected_at_factory(self):
        with pytest.raises(SubmissionError):
            make_submit_report_tool(SubmissionBox(), node_type="oracle")


class TestFallbackPath:
    async def test_fallback_when_never_called(self):
        box = SubmissionBox()
        submission = finalize_submission(
            box, final_text="  降级正文。", fallback_fields={"action": "持有"},
        )
        assert submission.source == SUBMISSION_FALLBACK
        assert submission.content == "降级正文。"
        assert submission.fields == {"action": "持有"}

    async def test_structured_box_returned_as_is(self):
        box = SubmissionBox()
        tool = make_submit_report_tool(box, node_type="analyst")
        await tool.handler(content="正式报告。")
        submission = finalize_submission(box, final_text="不应使用")
        assert submission.source == SUBMISSION_STRUCTURED
        assert submission.content == "正式报告。"

    async def test_fallback_commit_emits_with_marker(self):
        """降级提交走同一条 commit 路径（fallback_text 标记随事件落库）"""
        state: dict = {}
        sink = _CaptureSink()
        submission = finalize_submission(SubmissionBox(), final_text="降级报告。")
        await commit_submission(
            submission, state=state, report_key="market_report",
            event_sink=sink, agent_key="market", phase="analysts",
        )
        assert state["reports"]["market_report"] == "降级报告。"
        assert sink.events[0]["submission"] == SUBMISSION_FALLBACK

    async def test_empty_report_key_noop(self):
        state: dict = {}
        sink = _CaptureSink()
        await commit_submission(
            finalize_submission(SubmissionBox(), final_text="x"),
            state=state, report_key="", event_sink=sink,
        )
        assert "reports" not in state
        assert sink.events == []
