"""
测试工具管理 API

注意：这些测试需要完整的数据库和认证环境才能运行。
在本地开发环境中，建议手动测试 API 端点。
"""

import pytest


class TestMCPToolsAPI:
    """测试 MCP 工具管理 API - 占位测试"""

    def test_mcp_tools_api_structure(self):
        """验证 MCP 工具 API 结构存在"""
        from app.routers.tools import (
            list_mcp_tools,
            toggle_mcp_tool,
            get_mcp_availability_summary,
            _MCP_TOOLS
        )
        # 验证函数存在
        assert callable(list_mcp_tools)
        assert callable(toggle_mcp_tool)
        assert callable(get_mcp_availability_summary)
        # 验证工具列表有20个工具
        assert len(_MCP_TOOLS) == 20

    def test_mcp_tools_data_structure(self):
        """验证 MCP 工具数据结构"""
        from app.routers.tools import _MCP_TOOLS

        for tool in _MCP_TOOLS:
            assert "name" in tool
            assert "description" in tool
            assert "category" in tool
            assert "tushare_only" in tool

    def test_disabled_tools_file_handling(self):
        """验证禁用工具文件处理"""
        from app.routers.tools import _get_disabled_tools, _save_disabled_tools

        # 测试获取禁用工具（可能为空）
        disabled = _get_disabled_tools()
        assert isinstance(disabled, set)
