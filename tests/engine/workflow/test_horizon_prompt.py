"""期限贯通 prompt 注入测试：mid/long 注入锚点、short/None 零注入、state 键集不变。

红线（golden 基线零重生成）：horizon 不进 state 顶层键、不进事件序列——
本文件内置键集一致性断言局部复验该红线。
"""
from typing import Any, Dict, List, Optional

import pytest

from app.engine.orchestrator.pipeline import PipelineDeps, run_pipeline
from app.engine.prompts.horizon import build_horizon_anchor
from app.llm.core.base import BaseLLMClient, StreamEvent
from app.llm.core.types import (
    ChatResponse,
    Message,
    Role,
    StopReason,
    TextBlock,
    Usage,
)

BASKET = [
    "market-analyst",
    "financial-news-analyst",
    "china-market-analyst",
    "short-term-capital-analyst",
]

ANCHOR_MARK = "【投资期限指令"


class _RecordingClient(BaseLLMClient):
    """固定单轮回复并录制每次调用的 system prompt（真实子类，非 mock 库）"""

    protocol = "test"
    model = "test-model"

    def __init__(self, text: str):
        self._text = text
        self.systems: List[Optional[str]] = []

    async def chat(self, messages, system=None, **kwargs) -> ChatResponse:
        self.systems.append(system)
        return self._resp()

    async def chat_stream(self, messages, system=None, **kwargs):
        self.systems.append(system)
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


async def _run_with_horizon(horizon: Any):
    analyst = _RecordingClient("分析师报告：均线多头排列。")
    debate = _RecordingClient("阶段输出：综合判断为积极。")
    config: Dict[str, Any] = {
        "phase2_enabled": True,
        "phase3_enabled": False,
        "phase2_debate_rounds": 1,
    }
    if horizon is not None:
        config["horizon"] = horizon
    state = await run_pipeline(
        deps=PipelineDeps(analyst_client=analyst, debate_client=debate, toolkit=None, config=config),
        company_name="000001",
        trade_date="2026-10-28",
        selected_analysts=BASKET,
    )
    return state, analyst, debate


class TestAnchorBuilder:
    def test_short_and_none_return_empty(self):
        assert build_horizon_anchor(None, "trader") == ""
        assert build_horizon_anchor("short", "analyst") == ""
        assert build_horizon_anchor("bogus", "debater") == ""

    def test_mid_long_anchor_content(self):
        for horizon, n in (("mid", 20), ("long", 60)):
            for role in ("analyst", "debater", "judge", "trader"):
                a = build_horizon_anchor(horizon, role)
                assert ANCHOR_MARK in a
                assert f"{n} 个交易日" in a
        # trader 版逐条重解读硬文案
        t = build_horizon_anchor("mid", "trader")
        assert "未来 3 天每天买入价格区间" in t
        assert "未来 7 天每天卖出价格区间" in t
        assert "持有周期" in t
        assert "20 日均线破位" in t
        # long 版止损锚升级
        assert "60 日均线" in build_horizon_anchor("long", "trader")


@pytest.mark.asyncio
class TestPipelineInjection:
    async def test_mid_injects_all_roles(self):
        _, analyst, debate = await _run_with_horizon("mid")
        # 分析师（analyst client）与辩论链（debate client：trader 也走 debate_client）
        assert any(s and ANCHOR_MARK in s for s in analyst.systems), "分析师未注入期限锚点"
        assert any(s and ANCHOR_MARK in s for s in debate.systems), "trader/辩手未注入期限锚点"

    async def test_short_and_none_inject_nothing(self):
        for horizon in (None, "short"):
            _, analyst, debate = await _run_with_horizon(horizon)
            assert not any(s and ANCHOR_MARK in s for s in analyst.systems)
            assert not any(s and ANCHOR_MARK in s for s in debate.systems)

    async def test_state_top_level_keys_unchanged(self):
        """golden 红线局部复验：horizon 不进 state 顶层键集"""
        base_state, _, _ = await _run_with_horizon(None)
        mid_state, _, _ = await _run_with_horizon("mid")
        assert set(base_state.keys()) == set(mid_state.keys())
