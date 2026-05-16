"""
MCP 工具管理 API 测试

测试工具管理路由的功能、数据结构和端点行为。
直接调用真实的数据结构和函数，不使用 patch/MagicMock。
"""

import os
import json
import tempfile
import pytest


class TestMCPToolsAPI:
    """测试 MCP 工具管理 API 结构和数据"""

    def test_mcp_tools_api_structure(self):
        """验证 MCP 工具 API 函数存在且可调用"""
        from app.routers.tools import (
            list_mcp_tools,
            toggle_mcp_tool,
            get_mcp_availability_summary,
            _MCP_TOOLS,
        )
        assert callable(list_mcp_tools)
        assert callable(toggle_mcp_tool)
        assert callable(get_mcp_availability_summary)
        assert isinstance(_MCP_TOOLS, list)
        assert len(_MCP_TOOLS) == 20

    def test_mcp_tools_data_structure(self):
        """验证每个 MCP 工具具有完整的数据结构"""
        from app.routers.tools import _MCP_TOOLS

        required_keys = {"name", "description", "category", "tushare_only"}
        for i, tool in enumerate(_MCP_TOOLS):
            assert required_keys.issubset(tool.keys()), (
                f"Tool #{i} missing keys: {required_keys - tool.keys()}"
            )
            assert isinstance(tool["name"], str) and len(tool["name"]) > 0
            assert isinstance(tool["description"], str) and len(tool["description"]) > 0
            assert isinstance(tool["category"], str)
            assert isinstance(tool["tushare_only"], bool)

    def test_mcp_tool_names_are_unique(self):
        """验证工具名称唯一"""
        from app.routers.tools import _MCP_TOOLS

        names = [t["name"] for t in _MCP_TOOLS]
        assert len(names) == len(set(names)), "工具名称必须唯一"

    def test_disabled_tools_file_handling(self):
        """验证禁用工具文件读写"""
        from app.routers.tools import _get_disabled_tools

        disabled = _get_disabled_tools()
        assert isinstance(disabled, set)

    def test_disabled_tools_save_and_load(self, tmp_path):
        """验证禁用工具的保存和读取（使用临时文件）"""
        from app.routers.tools import _save_disabled_tools
        from pathlib import Path
        import app.routers.tools as tools_module

        # 备份原始文件路径
        original_file = tools_module._DISABLED_TOOLS_FILE

        try:
            # 使用临时文件替代
            temp_file = tmp_path / "disabled_tools.json"
            tools_module._DISABLED_TOOLS_FILE = temp_file

            test_tools = {"test_tool_1", "test_tool_2"}
            _save_disabled_tools(test_tools)

            # 验证文件内容
            assert temp_file.exists()
            with open(temp_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            assert set(data["disabled"]) == test_tools

        finally:
            # 恢复原始文件路径
            tools_module._DISABLED_TOOLS_FILE = original_file

    def test_mcp_tool_categories(self):
        """验证工具分类合理"""
        from app.routers.tools import _MCP_TOOLS

        categories = set(t["category"] for t in _MCP_TOOLS)
        assert len(categories) > 0, "应至少有一个工具分类"

    def test_router_has_correct_prefix_and_tags(self):
        """验证路由前缀和标签"""
        from app.routers.tools import router

        assert router.prefix == "/api/tools"
        assert router.tags is not None


class TestMCPToolsEndpoints:
    """测试 MCP 工具 API 端点行为"""

    @pytest.mark.asyncio
    async def test_list_available_tools_endpoint(self):
        """测试 GET /api/tools/available 端点定义"""
        from app.routers.tools import router

        routes = [r.path for r in router.routes]
        assert "/api/tools/available" in routes

    @pytest.mark.asyncio
    async def test_mcp_tools_endpoint(self):
        """测试 GET /api/tools/mcp 端点定义"""
        from app.routers.tools import router

        routes = [r.path for r in router.routes]
        assert "/api/tools/mcp" in routes

    @pytest.mark.asyncio
    async def test_toggle_mcp_tool_endpoint(self):
        """测试 PATCH /api/tools/mcp/{name}/toggle 端点定义"""
        from app.routers.tools import router

        routes = [r.path for r in router.routes]
        assert "/api/tools/mcp/{name}/toggle" in routes

    @pytest.mark.asyncio
    async def test_availability_summary_endpoint(self):
        """测试 GET /api/tools/mcp/availability-summary 端点定义"""
        from app.routers.tools import router

        routes = [r.path for r in router.routes]
        assert "/api/tools/mcp/availability-summary" in routes


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
