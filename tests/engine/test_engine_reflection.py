"""测试 Reflector 反思模块"""

import pytest
from unittest.mock import MagicMock, call

from app.engine.graph.reflection import Reflector


class TestReflectorInit:
    def test_init_stores_llm(self, mock_llm):
        r = Reflector(mock_llm)
        assert r.quick_thinking_llm is mock_llm

    def test_init_generates_reflection_prompt(self, mock_llm):
        r = Reflector(mock_llm)
        assert r.reflection_system_prompt is not None
        assert len(r.reflection_system_prompt) > 0
        assert "Reasoning" in r.reflection_system_prompt
        assert "Improvement" in r.reflection_system_prompt


class TestExtractCurrentSituation:
    def test_collects_all_report_fields(self, mock_llm):
        r = Reflector(mock_llm)
        state = {
            "market_report": "市场报告内容",
            "fundamentals_report": "基本面报告内容",
            "news_report": "新闻报告内容",
            "messages": [],
            "company_of_interest": "000001",
        }
        result = r._extract_current_situation(state)
        assert "市场报告内容" in result
        assert "基本面报告内容" in result
        assert "新闻报告内容" in result

    def test_ignores_empty_report_values(self, mock_llm):
        r = Reflector(mock_llm)
        state = {
            "market_report": "市场报告",
            "fundamentals_report": "",
            "news_report": None,
            "messages": [],
        }
        result = r._extract_current_situation(state)
        assert "市场报告" in result
        assert "基本面报告" not in result

    def test_no_reports_returns_empty(self, mock_llm):
        r = Reflector(mock_llm)
        state = {"messages": [], "company_of_interest": "000001"}
        result = r._extract_current_situation(state)
        assert result == ""


class TestReflectOnComponent:
    def test_calls_llm_with_correct_structure(self, mock_llm):
        r = Reflector(mock_llm)
        result = r._reflect_on_component("BULL", "看涨报告", "市场情况", "盈利5%")
        mock_llm.invoke.assert_called_once()
        call_args = mock_llm.invoke.call_args[0][0]
        assert len(call_args) == 2
        assert call_args[0][0] == "system"
        assert call_args[1][0] == "human"
        assert "盈利5%" in call_args[1][1]
        assert "看涨报告" in call_args[1][1]


class TestReflectBullResearcher:
    def test_extracts_bull_history_and_updates_memory(self, mock_llm, mock_memory, sample_agent_state):
        r = Reflector(mock_llm)
        r.reflect_bull_researcher(sample_agent_state, "盈利5%", mock_memory)
        mock_llm.invoke.assert_called_once()
        mock_memory.add_situations.assert_called_once()
        situations = mock_memory.add_situations.call_args[0][0]
        assert len(situations) == 1
        assert isinstance(situations[0], tuple)

    def test_uses_investment_debate_state(self, mock_llm, mock_memory, sample_agent_state):
        r = Reflector(mock_llm)
        r.reflect_bull_researcher(sample_agent_state, "盈利5%", mock_memory)
        call_args = mock_llm.invoke.call_args[0][0]
        human_msg = call_args[1][1]
        assert "看好市场" in human_msg


class TestReflectBearResearcher:
    def test_extracts_bear_history(self, mock_llm, mock_memory, sample_agent_state):
        r = Reflector(mock_llm)
        r.reflect_bear_researcher(sample_agent_state, "亏损3%", mock_memory)
        call_args = mock_llm.invoke.call_args[0][0]
        human_msg = call_args[1][1]
        assert "看空市场" in human_msg


class TestReflectTrader:
    def test_extracts_trader_investment_plan(self, mock_llm, mock_memory, sample_agent_state):
        sample_agent_state["trader_investment_plan"] = "建议买入100股"
        r = Reflector(mock_llm)
        r.reflect_trader(sample_agent_state, "盈利5%", mock_memory)
        call_args = mock_llm.invoke.call_args[0][0]
        human_msg = call_args[1][1]
        assert "建议买入100股" in human_msg


class TestReflectInvestJudge:
    def test_extracts_judge_decision_from_investment(self, mock_llm, mock_memory, sample_agent_state):
        r = Reflector(mock_llm)
        r.reflect_invest_judge(sample_agent_state, "盈利5%", mock_memory)
        call_args = mock_llm.invoke.call_args[0][0]
        human_msg = call_args[1][1]
        assert "裁决结果" in human_msg


class TestReflectRiskManager:
    def test_extracts_judge_decision_from_risk(self, mock_llm, mock_memory, sample_agent_state):
        r = Reflector(mock_llm)
        r.reflect_risk_manager(sample_agent_state, "亏损3%", mock_memory)
        call_args = mock_llm.invoke.call_args[0][0]
        human_msg = call_args[1][1]
        assert "风控裁决" in human_msg
