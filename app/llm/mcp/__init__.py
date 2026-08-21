"""MCP 客户端（官方 mcp SDK，参考 claude-code mcp-client 架构）"""

from .client import MCPManager
from .config import MCPServerConfig, expand_env
from .tools import discover_mcp_tools, mcp_tool_name

__all__ = ["MCPManager", "MCPServerConfig", "expand_env", "discover_mcp_tools", "mcp_tool_name"]
