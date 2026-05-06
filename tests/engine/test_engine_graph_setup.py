"""测试 GraphSetup 图构建"""

import pytest
from unittest.mock import MagicMock

from app.engine.graph.setup import GraphSetup
from app.engine.graph.conditional_logic import ConditionalLogic


class TestGraphSetupInit:
    @pytest.fixture
    def components(self):
        mock_llm = MagicMock()
        toolkit = MagicMock()
        memories = [MagicMock()] * 5
        cl = ConditionalLogic(max_debate_rounds=2, max_risk_discuss_rounds=3)
        return {
            "quick_thinking_llm": mock_llm,
            "deep_thinking_llm": mock_llm,
            "toolkit": toolkit,
            "bull_memory": memories[0],
            "bear_memory": memories[1],
            "trader_memory": memories[2],
            "invest_judge_memory": memories[3],
            "risk_manager_memory": memories[4],
            "conditional_logic": cl,
        }

    def test_stores_components(self, components):
        gs = GraphSetup(**components)
        assert gs.quick_thinking_llm is components["quick_thinking_llm"]
        assert gs.deep_thinking_llm is components["deep_thinking_llm"]
        assert gs.toolkit is components["toolkit"]
        assert gs.conditional_logic is components["conditional_logic"]


class TestFormatAnalystName:
    @pytest.fixture
    def gs(self):
        return GraphSetup.__new__(GraphSetup)

    def test_simple_key(self, gs):
        assert gs._format_analyst_name("market") == "Market"

    def test_underscore_key(self, gs):
        assert gs._format_analyst_name("financial_news") == "Financial_News"

    def test_multi_underscore(self, gs):
        result = gs._format_analyst_name("china_market_data")
        assert result == "China_Market_Data"

    def test_single_word(self, gs):
        assert gs._format_analyst_name("news") == "News"
