"""
工具管理器 - 已迁移到 MCP 格式

旧格式工具已移除，请使用:
    from app.engine.tools.mcp import load_local_mcp_tools
    tools = load_local_mcp_tools()
"""

import logging

logger = logging.getLogger(__name__)

_MCP_IMPORT_MSG = (
    "旧格式工具已移除。"
    "请使用 MCP 格式工具："
    "  from app.engine.tools.mcp import load_local_mcp_tools"
    "  tools = load_local_mcp_tools()"
)


def _deprecated_error():
    """引发弃用错误"""
    raise NotImplementedError(_MCP_IMPORT_MSG)


def create_project_news_tools(toolkit):
    """已弃用：请使用 load_local_mcp_tools()"""
    _deprecated_error()


def create_project_market_tools(toolkit):
    """已弃用：请使用 load_local_mcp_tools()"""
    _deprecated_error()


def create_project_fundamentals_tools(toolkit):
    """已弃用：请使用 load_local_mcp_tools()"""
    _deprecated_error()


def create_project_sentiment_tools(toolkit):
    """已弃用：请使用 load_local_mcp_tools()"""
    _deprecated_error()


def create_project_china_market_tools(toolkit):
    """已弃用：请使用 load_local_mcp_tools()"""
    _deprecated_error()


def create_project_tools(toolkit):
    """已弃用：请使用 load_local_mcp_tools()"""
    _deprecated_error()
