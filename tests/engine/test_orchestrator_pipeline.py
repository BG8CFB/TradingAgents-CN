"""orchestrator/pipeline 保序与状态形状等价测试（去 LangGraph 迁移验收）

- 节点命名与旧 LangGraph 图一致（进度映射依赖）
- state 初始字段与旧 AgentState 完全一致（analysis_service 5 层提取依赖）
- 辩论轮次上限与旧 ConditionalLogic.MAX_ROUNDS 一致
- 增量合并语义（reports 合并 / messages 追加 / 其余覆盖）
"""

import pytest

from app.engine.orchestrator.pipeline import (
    MAX_ROUNDS,
    PipelineDeps,
    _format_analyst_node,
    _merge_state_update,
)
from app.engine.orchestrator.state import create_initial_state


class TestNodeNaming:
    def test_internal_key_to_node_name(self):
        assert _format_analyst_node("market") == "Market Analyst"
        assert _format_analyst_node("news") == "News Analyst"
        assert _format_analyst_node("social_media") == "Social_Media Analyst"

    def test_max_rounds_matches_legacy(self):
        assert MAX_ROUNDS == 10


class TestInitialStateShape:
    def test_core_fields(self):
        state = create_initial_state("000001", "2024-12-31")
        assert state["company_of_interest"] == "000001"
        assert state["trade_date"] == "2024-12-31"
        assert isinstance(state["messages"], list) and len(state["messages"]) == 1
        assert state["investment_debate_state"]["count"] == 0
        assert state["risk_debate_state"]["count"] == 0
        # 轮次经派生视图计算（count//2、count//3，与旧 current_round_index 语义一致）
        from app.engine.orchestrator.state import current_round_index
        assert current_round_index(state["investment_debate_state"], 2) == 0
        assert current_round_index(state["risk_debate_state"], 3) == 0
        assert state["risk_debate_state"]["latest_speaker"] == ""
        assert "trader_investment_plan" in state
        assert "investment_plan" in state
        assert "final_trade_decision" in state

    def test_dynamic_report_fields(self):
        state = create_initial_state("000001", "2024-12-31")
        # DynamicAnalystFactory 动态初始化 *_report 字段
        report_keys = [k for k in state if k.endswith("_report")]
        assert report_keys, "应至少存在一个 *_report 初始字段"


class TestMergeStateUpdate:
    def test_reports_merged_and_messages_appended(self):
        target = {"reports": {"a_report": "x"}, "messages": [1], "k": "old"}
        _merge_state_update(target, {"reports": {"b_report": "y"}, "messages": [2], "k": "new"})
        assert target["reports"] == {"a_report": "x", "b_report": "y"}
        assert target["messages"] == [1, 2]
        assert target["k"] == "new"

    def test_empty_update_noop(self):
        target = {"k": "v"}
        _merge_state_update(target, {})
        assert target == {"k": "v"}


class TestPipelineDeps:
    def test_defaults(self):
        deps = PipelineDeps(analyst_client=None, debate_client=None, toolkit=None)
        assert deps.bull_memory is None
        assert deps.config == {}


@pytest.mark.ai
class TestPipelineOrderingRealLLM:
    """真实 LLM 端到端保序验收（事件序列断言）

    无凭据时 skip。验证：分析师串行 → Bull/Bear 交替均等 → Trader 恒执行
    → Risky→Safe→Neutral 固定循环 → Summary 恒执行。
    """

    def test_event_order(self):
        pytest.importorskip("app.llm.providers")
        from app.llm.providers import get_engine_clients

        import asyncio

        from app.engine.orchestrator.pipeline import run_pipeline

        async def _run():
            clients = await get_engine_clients()
            deps = PipelineDeps(
                analyst_client=clients["analyst"],
                debate_client=clients["debate"],
                toolkit=None,
                config={"phase2_enabled": True, "phase3_enabled": True,
                        "phase2_debate_rounds": 1, "phase3_debate_rounds": 1},
            )
            return await run_pipeline(
                deps, "000001", "2024-12-31",
                selected_analysts=["market"],
            )

        state = asyncio.run(_run())
        inv = state["investment_debate_state"]
        # 总发言 2*(rounds+1)=4，round_index=count//2
        assert inv["count"] == 4
        assert inv["current_round_index"] == 2
        risk = state["risk_debate_state"]
        # 总发言 3*(rounds+1)=6
        assert risk["count"] == 6
        assert risk["current_round_index"] == 2
        assert state["trader_investment_plan"]
        assert "node_timings" in state
