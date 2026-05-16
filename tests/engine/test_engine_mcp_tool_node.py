"""测试 MCP ToolNode 错误处理和工厂

调用真实的异常类、错误处理函数和工厂函数，
验证错误处理、ToolNode 创建和默认处理器行为。
"""

import pytest

from app.engine.tools.mcp.tool_node import (
    MCPToolError,
    DataSourceError,
    InvalidArgumentError,
    create_error_handler,
    create_tool_node,
    get_default_error_handler,
)


class TestExceptionHierarchy:
    def test_mcp_tool_error_is_exception(self):
        assert issubclass(MCPToolError, Exception)

    def test_data_source_error_inherits(self):
        assert issubclass(DataSourceError, MCPToolError)

    def test_invalid_argument_error_inherits(self):
        assert issubclass(InvalidArgumentError, MCPToolError)

    def test_can_catch_subclasses_with_base(self):
        try:
            raise DataSourceError("test")
        except MCPToolError:
            pass


class TestCreateErrorHandler:
    def test_timeout_error(self):
        handler = create_error_handler(include_suggestions=True, log_errors=False)
        result = handler(TimeoutError("timeout"))
        assert "超时" in result

    def test_connection_error(self):
        handler = create_error_handler(include_suggestions=True, log_errors=False)
        result = handler(ConnectionError("network"))
        assert "连接" in result

    def test_data_source_error(self):
        handler = create_error_handler(include_suggestions=True, log_errors=False)
        result = handler(DataSourceError("source"))
        assert "数据源" in result

    def test_invalid_argument_error(self):
        handler = create_error_handler(include_suggestions=True, log_errors=False)
        result = handler(InvalidArgumentError("bad arg"))
        assert "参数" in result

    def test_value_error(self):
        handler = create_error_handler(include_suggestions=True, log_errors=False)
        result = handler(ValueError("bad value"))
        assert "参数" in result

    def test_file_not_found_error(self):
        handler = create_error_handler(include_suggestions=True, log_errors=False)
        result = handler(FileNotFoundError("file"))
        assert "文件" in result

    def test_permission_error(self):
        handler = create_error_handler(include_suggestions=True, log_errors=False)
        result = handler(PermissionError("denied"))
        assert "权限" in result

    def test_generic_error(self):
        handler = create_error_handler(include_suggestions=True, log_errors=False)
        result = handler(RuntimeError("unknown"))
        assert "出错" in result

    def test_without_suggestions(self):
        handler = create_error_handler(include_suggestions=False, log_errors=False)
        result = handler(TimeoutError("timeout"))
        assert "建议" not in result

    def test_with_suggestions(self):
        handler = create_error_handler(include_suggestions=True, log_errors=False)
        result = handler(TimeoutError("timeout"))
        assert "建议" in result

    def test_includes_timestamp(self):
        handler = create_error_handler(include_suggestions=True, log_errors=False)
        result = handler(TimeoutError("timeout"))
        assert "时间:" in result

    def test_includes_error_type(self):
        handler = create_error_handler(include_suggestions=True, log_errors=False)
        result = handler(TimeoutError("timeout"))
        assert "TimeoutError" in result


class TestCreateToolNode:
    @pytest.fixture(autouse=True)
    def _make_real_tool(self):
        from langchain_core.tools import tool as lc_tool

        @lc_tool
        def dummy_tool(x: str) -> str:
            """A dummy tool for testing"""
            return x

        self._tool = dummy_tool

    def test_returns_tool_node_with_tools(self):
        result = create_tool_node([self._tool], handle_tool_errors=True)
        assert result is not None

    def test_returns_none_with_empty_tools(self):
        result = create_tool_node([], handle_tool_errors=True)
        assert result is None

    def test_with_string_error_handler(self):
        result = create_tool_node([self._tool], handle_tool_errors="custom error")
        assert result is not None

    def test_with_callable_error_handler(self):
        handler = lambda e: f"error: {e}"
        result = create_tool_node([self._tool], handle_tool_errors=handler)
        assert result is not None


class TestGetDefaultErrorHandler:
    def test_returns_callable(self):
        handler = get_default_error_handler()
        assert callable(handler)

    def test_handler_returns_string(self):
        handler = get_default_error_handler()
        result = handler(Exception("test"))
        assert isinstance(result, str)
        assert len(result) > 0
