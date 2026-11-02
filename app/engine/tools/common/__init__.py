"""
工具共享基础设施

提供所有工具类型（Builtin/MCP/Skill）共用的返回格式、格式化和参数验证。
"""

from .tool_result import ToolResult, success_result, no_data_result, error_result, format_tool_result, ErrorCodes
from .format import format_result
from .param_validators import MCPToolValidators, validate_symbol, validate_date, validate_limit, validate_period

# deprecated: validate_stock_code 旧名兼容 re-export，调用方应迁移到 validate_symbol
validate_stock_code = validate_symbol

__all__ = [
    # ToolResult
    "ToolResult",
    "success_result",
    "no_data_result",
    "error_result",
    "format_tool_result",
    "ErrorCodes",
    # Format
    "format_result",
    # Param Validators
    "MCPToolValidators",
    "validate_symbol",
    "validate_stock_code",  # deprecated
    "validate_date",
    "validate_limit",
    "validate_period",
]
