"""
MCP 工具统一标准

定义所有 AI 智能体调用的工具必须遵循的返回格式和规范。

目的：避免 AI 循环调用工具，确保返回格式标准化。
"""
import json
from typing import Optional, Literal, TypedDict, Union


class ToolResult(TypedDict):
    """
    统一的工具返回格式，用于 AI 智能体调用的所有工具。

    该格式确保 AI 能够明确区分成功、无数据和错误状态，避免循环调用。
    """
    status: Literal["success", "no_data", "error"]
    """状态标识：
    - success: 成功获取数据
    - no_data: 未找到数据（这是正常状态，AI 不应重试）
    - error: 发生错误（AI 可以根据建议决定是否重试）
    """

    data: str
    """返回的 Markdown 格式数据"""

    error_code: Optional[str]
    """错误代码，仅在 status=error 时有值"""

    suggestion: Optional[str]
    """给 AI 的建议，帮助 AI 决定下一步操作"""


def success_result(data: str) -> ToolResult:
    """创建成功结果"""
    return {
        "status": "success",
        "data": data,
        "error_code": None,
        "suggestion": None
    }


def no_data_result(
    message: str = "未找到相关数据",
    suggestion: str = "这是正常状态，不要重试或尝试其他参数"
) -> ToolResult:
    """创建无数据结果"""
    return {
        "status": "no_data",
        "data": message,
        "error_code": None,
        "suggestion": suggestion
    }


def error_result(
    error_code: str,
    message: str,
    suggestion: Optional[str] = None
) -> ToolResult:
    """创建错误结果"""
    return {
        "status": "error",
        "data": message,
        "error_code": error_code,
        "suggestion": suggestion or "检查输入参数后重试，或使用其他工具"
    }


def format_tool_result(result: Union[ToolResult, str]) -> str:
    """
    将 ToolResult 转换为 JSON 字符串供 AI 解析。

    为了向后兼容，如果传入的是字符串，直接返回。
    """
    if isinstance(result, str):
        return result
    return json.dumps(result, ensure_ascii=False, indent=2)


# 错误代码常量
class ErrorCodes:
    """标准错误代码定义"""
    MISSING_PARAM = "MISSING_PARAM"
    INVALID_PARAM = "INVALID_PARAM"
    DATA_FETCH_ERROR = "DATA_FETCH_ERROR"
    NETWORK_ERROR = "NETWORK_ERROR"
    PARSE_ERROR = "PARSE_ERROR"
    UNKNOWN_MARKET = "UNKNOWN_MARKET"
    STOCK_CODE_INVALID = "STOCK_CODE_INVALID"
