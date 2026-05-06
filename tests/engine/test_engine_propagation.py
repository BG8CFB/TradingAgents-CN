"""测试 Propagator 状态传播模块"""

import pytest
from unittest.mock import patch, MagicMock

from app.engine.graph.propagation import Propagator


class TestPropagatorInit:
    def test_default_max_recur_limit(self):
        p = Propagator()
        assert p.max_recur_limit == 100

    def test_custom_max_recur_limit(self):
        p = Propagator(max_recur_limit=50)
        assert p.max_recur_limit == 50


class TestCreateInitialState:
    def test_contains_required_keys(self):
        p = Propagator()
        with patch("app.engine.agents.analysts.dynamic_analyst.DynamicAnalystFactory") as mock_factory:
            mock_factory.get_all_agents.return_value = []
            state = p.create_initial_state("000001", "2024-12-31")

        assert "messages" in state
        assert "company_of_interest" in state
        assert "trade_date" in state
        assert "task_id" in state
        assert "investment_debate_state" in state
        assert "risk_debate_state" in state
        assert "reports" in state

    def test_company_name_set(self):
        p = Propagator()
        with patch("app.engine.agents.analysts.dynamic_analyst.DynamicAnalystFactory") as mock_factory:
            mock_factory.get_all_agents.return_value = []
            state = p.create_initial_state("600519", "2024-06-15")

        assert state["company_of_interest"] == "600519"
        assert state["trade_date"] == "2024-06-15"

    def test_task_id_set(self):
        p = Propagator()
        with patch("app.engine.agents.analysts.dynamic_analyst.DynamicAnalystFactory") as mock_factory:
            mock_factory.get_all_agents.return_value = []
            state = p.create_initial_state("000001", "2024-12-31", task_id="task-123")

        assert state["task_id"] == "task-123"

    def test_task_id_default_none(self):
        p = Propagator()
        with patch("app.engine.agents.analysts.dynamic_analyst.DynamicAnalystFactory") as mock_factory:
            mock_factory.get_all_agents.return_value = []
            state = p.create_initial_state("000001", "2024-12-31")

        assert state["task_id"] is None

    def test_investment_debate_state_fields(self):
        p = Propagator()
        with patch("app.engine.agents.analysts.dynamic_analyst.DynamicAnalystFactory") as mock_factory:
            mock_factory.get_all_agents.return_value = []
            state = p.create_initial_state("000001", "2024-12-31")

        ids = state["investment_debate_state"]
        assert "bull_history" in ids
        assert "bear_history" in ids
        assert "judge_decision" in ids
        assert ids["bull_history"] == ""
        assert ids["bear_history"] == ""

    def test_risk_debate_state_fields(self):
        p = Propagator()
        with patch("app.engine.agents.analysts.dynamic_analyst.DynamicAnalystFactory") as mock_factory:
            mock_factory.get_all_agents.return_value = []
            state = p.create_initial_state("000001", "2024-12-31")

        rds = state["risk_debate_state"]
        assert "risky_history" in rds
        assert "safe_history" in rds
        assert "neutral_history" in rds
        assert "judge_decision" in rds
        assert rds["risky_history"] == ""

    def test_initial_message_contains_company_and_date(self):
        p = Propagator()
        with patch("app.engine.agents.analysts.dynamic_analyst.DynamicAnalystFactory") as mock_factory:
            mock_factory.get_all_agents.return_value = []
            state = p.create_initial_state("000001", "2024-12-31")

        messages = state["messages"]
        assert len(messages) >= 1
        content = messages[0].content
        assert "000001" in content
        assert "2024-12-31" in content

    def test_reports_initialized_empty(self):
        p = Propagator()
        with patch("app.engine.agents.analysts.dynamic_analyst.DynamicAnalystFactory") as mock_factory:
            mock_factory.get_all_agents.return_value = []
            state = p.create_initial_state("000001", "2024-12-31")

        assert state["reports"] == {}

    def test_dynamic_agent_report_fields(self):
        p = Propagator()
        mock_agents = [
            {"slug": "market-analyst"},
            {"slug": "news-analyst"},
        ]
        with patch("app.engine.agents.analysts.dynamic_analyst.DynamicAnalystFactory") as mock_factory:
            mock_factory.get_all_agents.return_value = mock_agents
            state = p.create_initial_state("000001", "2024-12-31")

        assert "market_report" in state
        assert "market_tool_call_count" in state
        assert "news_report" in state
        assert "news_tool_call_count" in state

    def test_dynamic_init_failure_graceful(self):
        p = Propagator()
        with patch("app.engine.agents.analysts.dynamic_analyst.DynamicAnalystFactory") as mock_factory:
            mock_factory.get_all_agents.side_effect = Exception("加载失败")
            state = p.create_initial_state("000001", "2024-12-31")

        assert "reports" in state
        assert state["reports"] == {}


class TestGetGraphArgs:
    def test_with_progress_callback(self):
        p = Propagator(max_recur_limit=50)
        args = p.get_graph_args(use_progress_callback=True)
        assert args["stream_mode"] == "updates"
        assert args["config"]["recursion_limit"] == 50

    def test_without_progress_callback(self):
        p = Propagator(max_recur_limit=100)
        args = p.get_graph_args(use_progress_callback=False)
        assert args["stream_mode"] == "values"
        assert args["config"]["recursion_limit"] == 100

    def test_default_uses_values(self):
        p = Propagator()
        args = p.get_graph_args()
        assert args["stream_mode"] == "values"
