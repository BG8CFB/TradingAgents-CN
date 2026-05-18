"""
工具调用日志工具

提供统一的日志记录功能，用于记录工具调用、结果和错误。
"""
import logging
import functools
from typing import Any, Callable

logger = logging.getLogger(__name__)


def log_tool_call(
    tool_name: str = None,
    log_args: bool = False,
    log_result_length: bool = False,
    log_execution_time: bool = False,
):
    """
    工具调用日志装饰器。

    Args:
        tool_name: 工具名称（可选，默认使用函数名）
        log_args: 是否记录参数（默认关闭）
        log_result_length: 是否记录结果长度（默认关闭）
        log_execution_time: 是否记录执行时间（默认关闭）

    Returns:
        装饰器函数
    """

    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs) -> Any:
            name = tool_name or func.__name__

            try:
                result = func(*args, **kwargs)
                logger.info(f"[工具调用] {name} 执行成功")
                return result

            except Exception as e:
                logger.error(
                    f"[工具调用] {name} 执行失败: {type(e).__name__} - {str(e)}"
                )
                raise

        return wrapper

    return decorator


def log_mcp_server_startup(server_name: str, tool_names: list):
    """记录 MCP 服务器启动日志。"""
    logger.info(f"MCP服务器启动: {server_name} (工具数: {len(tool_names)})")


def log_mcp_server_shutdown(server_name: str):
    """记录 MCP 服务器关闭日志。"""
    logger.info(f"MCP服务器关闭: {server_name}")
