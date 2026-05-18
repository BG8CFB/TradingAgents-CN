"""测试 builtin/standard 统一标准"""

import json
import pytest

from app.engine.tools.common.tool_result import (
    ToolResult,
    success_result,
    no_data_result,
    error_result,
    format_tool_result,
    ErrorCodes,
)


class TestSuccessResult:
    def test_structure(self):
        r = success_result("数据内容")
        assert r["status"] == "success"
        assert r["data"] == "数据内容"
        assert r["error_code"] is None
        assert r["suggestion"] is None


class TestNoDataResult:
    def test_default_message(self):
        r = no_data_result()
        assert r["status"] == "no_data"
        assert "未找到" in r["data"]
        assert r["error_code"] is None

    def test_custom_message(self):
        r = no_data_result(message="无新闻数据", suggestion="尝试其他日期")
        assert r["data"] == "无新闻数据"
        assert r["suggestion"] == "尝试其他日期"


class TestErrorResult:
    def test_with_suggestion(self):
        r = error_result("ERR_001", "网络错误", suggestion="重试")
        assert r["status"] == "error"
        assert r["error_code"] == "ERR_001"
        assert r["data"] == "网络错误"
        assert r["suggestion"] == "重试"

    def test_without_suggestion(self):
        r = error_result("ERR_002", "解析失败")
        assert r["suggestion"] == "检查输入参数后重试，或使用其他工具"


class TestFormatToolResult:
    def test_tool_result_to_json(self):
        tr = success_result("测试")
        result = format_tool_result(tr)
        parsed = json.loads(result)
        assert parsed["status"] == "success"

    def test_string_passthrough(self):
        assert format_tool_result("原始字符串") == "原始字符串"


class TestErrorCodes:
    def test_all_codes_exist(self):
        assert ErrorCodes.MISSING_PARAM == "MISSING_PARAM"
        assert ErrorCodes.INVALID_PARAM == "INVALID_PARAM"
        assert ErrorCodes.DATA_FETCH_ERROR == "DATA_FETCH_ERROR"
        assert ErrorCodes.NETWORK_ERROR == "NETWORK_ERROR"
        assert ErrorCodes.PARSE_ERROR == "PARSE_ERROR"
        assert ErrorCodes.UNKNOWN_MARKET == "UNKNOWN_MARKET"
        assert ErrorCodes.STOCK_CODE_INVALID == "STOCK_CODE_INVALID"
