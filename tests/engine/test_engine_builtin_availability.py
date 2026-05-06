"""测试 builtin/availability 工具可用性检测"""

import pytest
from unittest.mock import patch

from app.engine.tools.builtin.availability import (
    check_tool_availability,
    check_all_tools_availability,
    get_availability_summary,
)


class TestCheckToolAvailability:
    @patch("app.engine.tools.builtin.availability.get_available_data_sources", return_value={"akshare", "tushare"})
    def test_no_requirements_always_available(self, mock_sources):
        assert check_tool_availability("any_tool", {}) is True

    @patch("app.engine.tools.builtin.availability.get_available_data_sources", return_value={"akshare"})
    def test_matching_source_available(self, mock_sources):
        ds_map = {"get_stock_data": ["tushare", "akshare"]}
        assert check_tool_availability("get_stock_data", ds_map) is True

    @patch("app.engine.tools.builtin.availability.get_available_data_sources", return_value={"akshare"})
    def test_no_matching_source_unavailable(self, mock_sources):
        ds_map = {"get_finnhub_news": ["finnhub"]}
        assert check_tool_availability("get_finnhub_news", ds_map) is False

    @patch("app.engine.tools.builtin.availability.get_available_data_sources", return_value=set())
    def test_empty_sources_all_unavailable(self, mock_sources):
        ds_map = {"tool_a": ["tushare"]}
        assert check_tool_availability("tool_a", ds_map) is False


class TestCheckAllToolsAvailability:
    @patch("app.engine.tools.builtin.availability.get_available_data_sources", return_value={"akshare"})
    def test_batch_check(self, mock_sources):
        ds_map = {
            "tool_a": ["akshare"],
            "tool_b": ["finnhub"],
            "tool_c": [],
        }
        result = check_all_tools_availability(ds_map)
        assert result["tool_a"] is True
        assert result["tool_b"] is False
        assert result["tool_c"] is True


class TestGetAvailabilitySummary:
    @patch("app.engine.tools.builtin.availability.get_available_data_sources", return_value={"akshare"})
    def test_summary_structure(self, mock_sources):
        ds_map = {
            "tool_a": ["akshare"],
            "tool_b": ["finnhub"],
        }
        summary = get_availability_summary(ds_map)
        assert summary["total"] == 2
        assert summary["available"] == 1
        assert summary["unavailable"] == 1
        assert "akshare" in summary["available_sources"]
        assert "details" in summary
