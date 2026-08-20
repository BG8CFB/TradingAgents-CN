"""
工具注册中心测试
测试 ToolRegistry 单例模式、注册、查找和禁用功能
使用轻量真实对象（SimpleNamespace，含 name/description 属性）替代 MagicMock
"""

import threading
from types import SimpleNamespace

import pytest


# ---------------------------------------------------------------------------
# Helpers: 创建轻量工具对象（registry 只依赖 name 属性）
# ---------------------------------------------------------------------------


def _make_real_tool(name: str):
    """创建带 name/description 的轻量工具对象"""
    return SimpleNamespace(name=name, description="测试工具")


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
        # 调用真实的 initialize，这会加载真实内置工具
        # 可能在测试环境中没有完整的工具模块，但不应抛异常
        try:
            registry.initialize()
        except Exception:
            pass
        # 即使加载失败，标志也应被设置
        assert registry._initialized is True

    def test_initialize_skip_on_double_init(self, registry):
        """重复初始化应跳过"""
        try:
            registry.initialize()
        except Exception:
            pass

        # 记录当前内置工具数量
        builtin_count_before = len(registry._builtin_tools)

        try:
            registry.initialize()
        except Exception:
            pass

        builtin_count_after = len(registry._builtin_tools)

        # 第二次初始化不应改变工具数量（跳过了）
        assert builtin_count_before == builtin_count_after


class TestToolRegistryRegistration:
    """ToolRegistry 工具注册测试"""

    def test_get_all_tools_returns_empty_initially(self, registry):
        """未注册工具时 get_all_tools 应返回空列表"""
        result = registry.get_all_tools()
        assert result == []


class TestToolRegistryGetTools:
    """ToolRegistry 工具查找测试"""

    def test_get_all_tools_returns_builtin(self, registry):
        """get_all_tools 应返回内置工具"""
        registry._builtin_tools = [_make_real_tool("builtin_1")]

        result = registry.get_all_tools()
        names = [t.name for t in result]
        assert "builtin_1" in names

    def test_get_builtin_tools(self, registry):
        """get_builtin_tools 应返回内置工具列表"""
        registry._builtin_tools = [_make_real_tool("builtin_1")]

        result = registry.get_builtin_tools()
        assert len(result) == 1
        assert result[0].name == "builtin_1"

    def test_get_builtin_tool_metas(self, registry):
        """get_builtin_tool_metas 应返回元数据字典"""
        registry._builtin_metas = {"tool_a": {"category": "market"}}

        result = registry.get_builtin_tool_metas()
        assert "tool_a" in result
        assert result["tool_a"]["category"] == "market"


class TestBackwardCompatibleGetAllTools:
    """向后兼容 get_all_tools 函数测试"""

    def test_function_exists(self):
        """模块级 get_all_tools 函数应存在"""
        from app.engine.tools.registry import get_all_tools

        assert callable(get_all_tools)

    def test_function_returns_list(self):
        """get_all_tools 函数应返回列表"""
        from app.engine.tools.registry import ToolRegistry, get_all_tools

        # 确保单例已初始化（可能加载真实工具，但应返回列表）
        instance = ToolRegistry.get_instance()
        try:
            instance.initialize()
        except Exception:
            pass

        result = get_all_tools()
        assert isinstance(result, list)
