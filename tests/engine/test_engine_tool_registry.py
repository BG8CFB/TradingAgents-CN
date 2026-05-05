"""
工具注册中心测试
测试 ToolRegistry 单例模式、注册、查找和禁用功能
"""

import threading
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def reset_registry():
    """每个测试前后重置 ToolRegistry 全局单例"""
    from app.engine.tools.registry import ToolRegistry
    ToolRegistry.reset_instance()
    yield
    ToolRegistry.reset_instance()


@pytest.fixture
def registry():
    """获取全新的 ToolRegistry 实例"""
    from app.engine.tools.registry import ToolRegistry
    return ToolRegistry.get_instance()


def _make_mock_tool(name: str):
    """创建模拟工具"""
    tool = MagicMock()
    tool.name = name
    return tool


# ---------------------------------------------------------------------------
# Test Classes
# ---------------------------------------------------------------------------

class TestToolRegistrySingleton:
    """ToolRegistry 单例模式测试"""

    def test_get_instance_returns_same_object(self):
        """多次获取应返回同一实例"""
        from app.engine.tools.registry import ToolRegistry

        instance1 = ToolRegistry.get_instance()
        instance2 = ToolRegistry.get_instance()
        assert instance1 is instance2

    def test_get_instance_returns_tool_registry(self):
        """get_instance 应返回 ToolRegistry 类型"""
        from app.engine.tools.registry import ToolRegistry

        instance = ToolRegistry.get_instance()
        assert isinstance(instance, ToolRegistry)

    def test_reset_instance_creates_new(self):
        """reset_instance 后应创建新实例"""
        from app.engine.tools.registry import ToolRegistry

        instance1 = ToolRegistry.get_instance()
        ToolRegistry.reset_instance()
        instance2 = ToolRegistry.get_instance()
        assert instance1 is not instance2

    def test_singleton_thread_safety(self):
        """多线程获取单例应安全"""
        from app.engine.tools.registry import ToolRegistry

        results = []
        barrier = threading.Barrier(10)

        def get_and_store():
            barrier.wait()
            results.append(ToolRegistry.get_instance())

        threads = [threading.Thread(target=get_and_store) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # 所有线程应获得同一实例
        assert all(r is results[0] for r in results)


class TestToolRegistryInitialization:
    """ToolRegistry 初始化测试"""

    def test_initial_state_not_initialized(self, registry):
        """初始状态应为未初始化"""
        assert registry._initialized is False

    def test_initialize_sets_initialized_flag(self, registry):
        """初始化后应设置 initialized 标志"""
        with patch.object(registry, "_load_builtin_tools"), \
             patch.object(registry, "_load_skill_meta_tool"):
            registry.initialize()

        assert registry._initialized is True

    def test_initialize_skip_on_double_init(self, registry):
        """重复初始化应跳过"""
        with patch.object(registry, "_load_builtin_tools") as mock_load, \
             patch.object(registry, "_load_skill_meta_tool"):
            registry.initialize()
            registry.initialize()

        # _load_builtin_tools 只应被调用一次
        assert mock_load.call_count == 1


class TestToolRegistryRegistration:
    """ToolRegistry 工具注册测试"""

    def test_set_mcp_tools(self, registry):
        """set_mcp_tools 应设置 MCP 工具列表"""
        tools = [_make_mock_tool("mcp_tool_1"), _make_mock_tool("mcp_tool_2")]
        registry.set_mcp_tools(tools)

        assert len(registry._mcp_tools) == 2

    def test_set_mcp_tools_with_empty_list(self, registry):
        """set_mcp_tools 传入空列表应清空"""
        registry.set_mcp_tools([_make_mock_tool("t1")])
        registry.set_mcp_tools([])

        assert len(registry._mcp_tools) == 0

    def test_set_mcp_tools_with_none(self, registry):
        """set_mcp_tools 传入 None 应清空"""
        registry.set_mcp_tools(None)
        assert len(registry._mcp_tools) == 0

    def test_get_all_tools_returns_empty_initially(self, registry):
        """未注册工具时 get_all_tools 应返回空列表"""
        result = registry.get_all_tools()
        assert result == []


class TestToolRegistryGetTools:
    """ToolRegistry 工具查找测试"""

    def test_get_all_tools_combines_sources(self, registry):
        """get_all_tools 应合并所有来源的工具"""
        registry._builtin_tools = [_make_mock_tool("builtin_1")]
        registry._mcp_tools = [_make_mock_tool("mcp_1")]
        registry._skill_tools = [_make_mock_tool("skill_1")]

        result = registry.get_all_tools()
        names = [t.name for t in result]
        assert "builtin_1" in names
        assert "mcp_1" in names
        assert "skill_1" in names

    def test_get_all_tools_excludes_disabled(self, registry):
        """get_all_tools 应排除被禁用的工具"""
        registry._builtin_tools = [_make_mock_tool("enabled"), _make_mock_tool("disabled")]
        registry._disabled_tools = {"disabled"}

        result = registry.get_all_tools()
        names = [t.name for t in result]
        assert "enabled" in names
        assert "disabled" not in names

    def test_get_tools_by_names_returns_matching(self, registry):
        """get_tools_by_names 应返回匹配名称的工具"""
        registry._builtin_tools = [
            _make_mock_tool("tool_a"),
            _make_mock_tool("tool_b"),
            _make_mock_tool("tool_c"),
        ]

        result = registry.get_tools_by_names(["tool_a", "tool_c"])
        names = [t.name for t in result]
        assert "tool_a" in names
        assert "tool_c" in names
        assert "tool_b" not in names

    def test_get_tools_by_names_empty_returns_all(self, registry):
        """get_tools_by_names 传入空列表应返回所有工具"""
        registry._builtin_tools = [_make_mock_tool("tool_a"), _make_mock_tool("tool_b")]

        result = registry.get_tools_by_names([])
        assert len(result) == 2

    def test_get_tools_by_names_none_returns_all(self, registry):
        """get_tools_by_names 传入 None 应返回所有工具"""
        registry._builtin_tools = [_make_mock_tool("tool_a")]

        result = registry.get_tools_by_names(None)
        assert len(result) == 1

    def test_get_tools_by_names_no_match_returns_all(self, registry):
        """get_tools_by_names 无匹配时回退返回所有工具"""
        registry._builtin_tools = [_make_mock_tool("tool_a"), _make_mock_tool("tool_b")]

        result = registry.get_tools_by_names(["nonexistent"])
        assert len(result) == 2

    def test_get_builtin_tools(self, registry):
        """get_builtin_tools 应返回内置工具列表"""
        registry._builtin_tools = [_make_mock_tool("builtin_1")]

        result = registry.get_builtin_tools()
        assert len(result) == 1
        assert result[0].name == "builtin_1"

    def test_get_builtin_tool_metas(self, registry):
        """get_builtin_tool_metas 应返回元数据字典"""
        registry._builtin_metas = {"tool_a": {"category": "market"}}

        result = registry.get_builtin_tool_metas()
        assert "tool_a" in result
        assert result["tool_a"]["category"] == "market"


class TestToolRegistryToggle:
    """ToolRegistry 工具启用/禁用测试"""

    def test_toggle_tool_disable(self, registry):
        """禁用工具应添加到 disabled 集合"""
        registry.toggle_tool("test_tool", enabled=False)
        assert "test_tool" in registry._disabled_tools

    def test_toggle_tool_enable(self, registry):
        """启用工具应从 disabled 集合中移除"""
        registry._disabled_tools.add("test_tool")
        registry.toggle_tool("test_tool", enabled=True)
        assert "test_tool" not in registry._disabled_tools

    def test_toggle_tool_enable_idempotent(self, registry):
        """重复启用同一工具不应出错"""
        registry.toggle_tool("test_tool", enabled=True)
        registry.toggle_tool("test_tool", enabled=True)
        assert "test_tool" not in registry._disabled_tools

    def test_disabled_tools_tracks_multiple(self, registry):
        """应能同时禁用多个工具"""
        registry.toggle_tool("tool_a", enabled=False)
        registry.toggle_tool("tool_b", enabled=False)
        assert "tool_a" in registry._disabled_tools
        assert "tool_b" in registry._disabled_tools

    def test_get_availability_summary_includes_disabled(self, registry):
        """get_availability_summary 应包含禁用工具列表"""
        registry._disabled_tools = {"tool_a", "tool_b"}
        registry._builtin_metas = {}

        with patch("app.engine.tools.registry.ToolRegistry.get_availability_summary", wraps=registry.get_availability_summary):
            summary = registry.get_availability_summary()

        assert "disabled" in summary
        assert sorted(summary["disabled"]) == ["tool_a", "tool_b"]


class TestBackwardCompatibleGetAllTools:
    """向后兼容 get_all_tools 函数测试"""

    def test_function_exists(self):
        """模块级 get_all_tools 函数应存在"""
        from app.engine.tools.registry import get_all_tools
        assert callable(get_all_tools)

    def test_function_returns_list(self):
        """get_all_tools 函数应返回列表"""
        from app.engine.tools.registry import ToolRegistry, get_all_tools

        # 确保单例已初始化
        instance = ToolRegistry.get_instance()
        with patch.object(instance, "_load_builtin_tools"), \
             patch.object(instance, "_load_skill_meta_tool"):
            instance.initialize()

        result = get_all_tools()
        assert isinstance(result, list)
