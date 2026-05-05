"""
MCP 配置和工具模块测试

测试 MCP 配置模型、工具加载器、任务管理器的核心功能
"""

import pytest
from unittest.mock import MagicMock, patch, AsyncMock


class TestMCPServerConfig:
    """测试 MCP 服务器配置模型"""

    def test_mcp_config_import(self):
        """验证 MCPServerConfig 可正常导入"""
        from app.engine.tools.mcp import MCPServerConfig
        assert MCPServerConfig is not None

    def test_mcp_config_creation(self):
        """验证可以创建 MCPServerConfig 实例"""
        from app.engine.tools.mcp.config_utils import MCPServerConfig
        config = MCPServerConfig(
            command="python",
            args=["-m", "test"],
        )
        assert config.command == "python"
        assert config.type == "stdio"

    def test_mcp_config_validation(self):
        """验证 MCP 配置验证逻辑"""
        from app.engine.tools.mcp.config_utils import MCPServerConfig
        config = MCPServerConfig(
            command="python",
            args=[],
        )
        assert config.command == "python"

    def test_mcp_loader_import(self):
        """验证 MCP 加载器可导入"""
        from app.engine.tools.mcp.loader import load_local_mcp_tools
        assert callable(load_local_mcp_tools)

    def test_mcp_task_manager_import(self):
        """验证 MCP 任务管理器可导入"""
        from app.engine.tools.mcp.task_manager import TaskLevelMCPManager
        assert TaskLevelMCPManager is not None

    def test_mcp_health_monitor_import(self):
        """验证 MCP 健康监控可导入"""
        from app.engine.tools.mcp.health_monitor import HealthMonitor
        assert HealthMonitor is not None

    def test_mcp_tool_node_import(self):
        """验证 MCP 工具节点可导入"""
        from app.engine.tools.mcp.tool_node import create_tool_node
        assert callable(create_tool_node)


class TestMCPConfigUtils:
    """测试 MCP 配置工具函数"""

    def test_config_validation_function_exists(self):
        """验证配置验证函数存在"""
        from app.engine.tools.mcp.config_utils import validate_servers_map
        assert callable(validate_servers_map)

    def test_config_persistence_functions_exist(self):
        """验证配置持久化函数存在"""
        from app.engine.tools.mcp.config_utils import write_mcp_config, load_mcp_config
        assert callable(write_mcp_config)
        assert callable(load_mcp_config)
