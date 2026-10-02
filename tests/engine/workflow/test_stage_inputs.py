"""P3-f 声明化消费专项测试。

- 编译产物（PlannedDebate/PlannedSingle）携带 stage inputs 声明
- resolve_inputs 取值严格限于声明集（黑板中未声明的报告键不进入下游输入）
- 节点侧：researcher prompt 只含声明内报告；trader judge_decision 缺槽走兜底文案
"""

import pytest

from app.engine.orchestrator.workflow.compiler import compile_workflow
from app.engine.orchestrator.workflow.inputs import resolve_inputs
from app.engine.orchestrator.workflow.loader import load_default_spec
from app.engine.orchestrator.workflow.spec import CompileParams
from app.llm.core.base import BaseLLMClient, StreamEvent
from app.llm.core.types import ChatResponse, Message, Role, StopReason


class RecordingLLM(BaseLLMClient):
    """记录调用消息的 LLM（真实类）"""

    protocol = "openai"
    model = "recording-model"

    def __init__(self, response_text="回复内容"):
        self.calls = []
        self.response_text = response_text

    async def chat(self, messages, *, system=None, **kwargs):
        self.calls.append({"messages": list(messages), "system": system})
        return ChatResponse(
            message=Message(role=Role.ASSISTANT, content=self.response_text),
            stop_reason=StopReason.END_TURN,
        )

    async def chat_stream(self, messages, *, system=None, **kwargs):
        resp = await self.chat(messages, system=system)
        yield StreamEvent("message", response=resp)

    async def count_tokens(self, messages):
        return 1


def _compiled_plan():
    spec, _ = load_default_spec()
    params = CompileParams(selected_nodes=("market-analyst", "short-term-capital-analyst"))
    return compile_workflow(spec, params)


class TestPlanCarriesInputs:
    """编译产物携带 inputs 声明（executor 快照的数据来源）"""

    def test_debate_and_single_stages_carry_inputs(self):
        plan = _compiled_plan()
        by_id = {s.stage_id: s for s in plan.stages}

        research = by_id["research_debate"]
        slots = dict(research.inputs)
        assert set(slots["analyst_reports"]) >= {
            "market_report",
            "short_term_capital_report",
        }

        trader_slots = dict(by_id["trader"].inputs)
        assert trader_slots["judge_decision"] == "investment_debate_state.judge_decision"

        summary_slots = dict(by_id["summary"].inputs)
        assert summary_slots["risk_debate_history"] == "risk_debate_state"
        assert summary_slots["trader_plan"] == "trader_investment_plan"

    def test_batch_stage_has_no_inputs(self):
        from app.engine.orchestrator.workflow.plan import PlannedBatch

        plan = _compiled_plan()
        batch = next(s for s in plan.stages if isinstance(s, PlannedBatch))
        assert not getattr(batch, "inputs", ())


class TestResolveScopedToDeclaration:
    """resolve_inputs 取值严格限于声明集（P3-f 语义翻转的核心断言）"""

    def test_out_of_declaration_reports_excluded(self):
        plan = _compiled_plan()
        trader_stage = next(s for s in plan.stages if s.stage_id == "trader")
        state = {
            "reports": {
                "market_report": "IN_SCOPE",
                "custom_report": "OUT_OF_SCOPE",
            },
            "investment_debate_state": {"judge_decision": "JUDGE_DECISION"},
        }
        resolved = resolve_inputs(dict(trader_stage.inputs), state)

        assert resolved["analyst_reports"] == {"market_report": "IN_SCOPE"}
        assert "custom_report" not in resolved["analyst_reports"]
        assert resolved["judge_decision"] == "JUDGE_DECISION"

    def test_missing_judge_field_resolves_none(self):
        plan = _compiled_plan()
        trader_stage = next(s for s in plan.stages if s.stage_id == "trader")
        resolved = resolve_inputs(dict(trader_stage.inputs), {"reports": {}})
        assert resolved["judge_decision"] is None
        assert resolved["analyst_reports"] == {}

    def test_summary_debate_state_binding_resolves_dict(self):
        plan = _compiled_plan()
        summary_stage = next(s for s in plan.stages if s.stage_id == "summary")
        debate = {"rounds": [{"risky": "R"}], "count": 1}
        state = {
            "reports": {},
            "risk_debate_state": debate,
        }
        resolved = resolve_inputs(dict(summary_stage.inputs), state)
        assert resolved["risk_debate_history"] == debate


class TestNodeConsumesDeclaration:
    """节点侧消费集 = 声明集（黑名单动态收集退役后的行为锁定）"""

    @pytest.mark.asyncio
    async def test_researcher_prompt_contains_only_declared_reports(self):
        from app.engine.agents.stage_2.researcher_factory import create_researcher

        llm = RecordingLLM("多头论点：趋势向好。")
        node = create_researcher(llm, None, side="bull")
        state = {
            "company_of_interest": "000001",
            "trade_date": "2024-12-31",
            "investment_debate_state": {"rounds": [], "count": 0},
            "_stage_inputs": {"analyst_reports": {"market_report": "IN_SCOPE_MARKER"}},
            # 黑板含声明外的报告键（模拟自定义分析师产出）——不得进入辩手上下文
            "reports": {
                "market_report": "IN_SCOPE_MARKER",
                "custom_report": "OUT_OF_SCOPE_MARKER",
            },
        }
        update = await node(state)

        prompt_text = " ".join(m.content for m in llm.calls[0]["messages"] if hasattr(m, "content"))
        assert "IN_SCOPE_MARKER" in prompt_text
        assert "OUT_OF_SCOPE_MARKER" not in prompt_text
        assert update["reports"]["bull_researcher"]

    @pytest.mark.asyncio
    async def test_trader_judge_decision_fallback_when_slot_missing(self):
        from app.engine.agents.stage_2.trader import create_trader

        llm = RecordingLLM("投资计划：分批建仓。")
        node = create_trader(llm, None)
        state = {
            "company_of_interest": "000001",
            "_stage_inputs": {"analyst_reports": {}, "judge_decision": None},
        }
        update = await node(state)

        prompt_text = " ".join(m.content for m in llm.calls[0]["messages"] if hasattr(m, "content"))
        assert "暂无研究部主管裁决" in prompt_text
        assert update["trader_investment_plan"]

    @pytest.mark.asyncio
    async def test_debator_reads_trader_plan_from_slot(self):
        from app.engine.agents.stage_3.debator_factory import create_debator

        llm = RecordingLLM("激进观点：机会大于风险。")
        node = create_debator(llm, side="risky")
        state = {
            "company_of_interest": "000001",
            "trade_date": "2024-12-31",
            "risk_debate_state": {"rounds": [], "count": 0},
            "_stage_inputs": {
                "analyst_reports": {},
                "trader_plan": "TRADER_PLAN_MARKER",
            },
        }
        await node(state)

        prompt_text = " ".join(m.content for m in llm.calls[0]["messages"] if hasattr(m, "content"))
        assert "TRADER_PLAN_MARKER" in prompt_text
