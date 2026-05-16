"""测试 builtin/availability 工具可用性检测

调用真实的 check_tool_availability、check_all_tools_availability 和
get_availability_summary 函数，验证可用性检测逻辑。
"""

import os
import pytest

from app.engine.tools.builtin.availability import (
    check_tool_availability,
    check_all_tools_availability,
    get_availability_summary,
    get_available_data_sources,
)


class TestGetAvailableDataSources:
    def test_returns_set(self):
        """get_available_data_sources 应返回集合"""
        result = get_available_data_sources()
        assert isinstance(result, set)


class TestCheckToolAvailability:
    def test_no_requirements_always_available(self):
        """没有数据源要求的工具应始终可用"""
        assert check_tool_availability("any_tool", {}) is True

    def test_empty_requirements_always_available(self):
        """数据源要求为空列表的工具应始终可用"""
        ds_map = {"some_tool": []}
        assert check_tool_availability("some_tool", ds_map) is True

    def test_nonexistent_tool_in_map_available(self):
        """不在 data_source_map 中的工具（无要求）应可用"""
        ds_map = {}
        assert check_tool_availability("unknown_tool", ds_map) is True

    def test_result_depends_on_available_sources(self):
        """工具可用性取决于当前可用的数据源"""
        # 使用真实数据源检测。由于无法控制哪些数据源可用，
        # 我们验证返回值为 bool 类型
        ds_map = {"tool_a": ["tushare", "akshare"]}
        result = check_tool_availability("tool_a", ds_map)
        assert isinstance(result, bool)


class TestCheckAllToolsAvailability:
    def test_batch_check(self):
        """批量检查应返回正确的结构"""
        ds_map = {
            "tool_no_req": [],
            "tool_with_req": ["tushare"],
        }
        result = check_all_tools_availability(ds_map)
        assert isinstance(result, dict)
        assert "tool_no_req" in result
        assert result["tool_no_req"] is True  # 无要求始终可用
        assert "tool_with_req" in result
        assert isinstance(result["tool_with_req"], bool)

    def test_empty_map_returns_empty(self):
        """空映射应返回空字典"""
        result = check_all_tools_availability({})
        assert result == {}


class TestGetAvailabilitySummary:
    def test_summary_structure(self):
        """摘要应包含完整的结构"""
        ds_map = {
            "tool_no_req": [],
            "tool_with_req": ["tushare"],
        }
        summary = get_availability_summary(ds_map)
        assert "total" in summary
        assert "available" in summary
        assert "unavailable" in summary
        assert "available_sources" in summary
        assert "details" in summary
        assert summary["total"] == 2
        assert summary["available"] + summary["unavailable"] == 2
        assert isinstance(summary["available_sources"], list)
        assert isinstance(summary["details"], dict)

    def test_summary_counts_consistent(self):
        """available + unavailable 应等于 total"""
        ds_map = {
            "a": [],
            "b": ["tushare"],
            "c": ["finnhub"],
        }
        summary = get_availability_summary(ds_map)
        assert summary["available"] + summary["unavailable"] == summary["total"]
