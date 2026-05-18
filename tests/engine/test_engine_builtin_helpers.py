"""测试 builtin/helpers 辅助函数"""

import pytest

from app.engine.tools.common.format import format_result


class TestFormatResultNone:
    def test_none_returns_no_data(self):
        result = format_result(None, "标题")
        assert "No data found" in result
        assert "标题" in result


class TestFormatResultEmptyList:
    def test_empty_list_returns_no_data(self):
        result = format_result([], "标题")
        assert "No data found" in result


class TestFormatResultString:
    def test_plain_string_returned(self):
        result = format_result("内容文本", "标题")
        assert result == "内容文本"

    def test_markdown_table_not_truncated_when_short(self):
        table = "| col |\n|---|\n| val |"
        result = format_result(table, "标题")
        assert result == table


class TestFormatResultDictList:
    def test_creates_markdown_table(self):
        data = [
            {"name": "平安银行", "code": "000001"},
            {"name": "万科A", "code": "000002"},
        ]
        result = format_result(data, "股票列表")
        assert "股票列表" in result
        assert "平安银行" in result
        assert "000002" in result
        assert "|" in result

    def test_truncates_long_list(self):
        data = [{"id": i} for i in range(3000)]
        result = format_result(data, "长列表", max_rows=100)
        assert "剩余" in result


class TestFormatResultOther:
    def test_non_standard_type(self):
        result = format_result(42, "数值")
        assert "42" in result
