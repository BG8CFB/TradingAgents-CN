"""测试 builtin/loader 工具加载器

调用真实的 load_builtin_tools 和 get_builtin_tool_metas 函数，
验证内置工具模块的加载行为。
"""

import pytest

from app.engine.tools.builtin.loader import _DOMAIN_MODULES, load_builtin_tools, get_builtin_tool_metas


class TestDomainModules:
    def test_contains_expected_modules(self):
        """应包含所有预期的领域模块"""
        expected = [
            "market", "news", "fundamentals", "sentiment",
            "china_market", "capital_flow", "macro", "fund", "others",
        ]
        for mod in expected:
            assert mod in _DOMAIN_MODULES

    def test_count_is_nine(self):
        """领域模块数量应为 9"""
        assert len(_DOMAIN_MODULES) == 9


class TestLoadBuiltinTools:
    def test_returns_list(self):
        """load_builtin_tools 应返回列表"""
        result = load_builtin_tools()
        assert isinstance(result, list)

    def test_tool_items_are_callable(self):
        """加载的工具对象应具有 name 属性"""
        result = load_builtin_tools()
        # 在测试环境中可能某些模块不可用
        for tool in result:
            assert hasattr(tool, "name")
            assert isinstance(tool.name, str)


class TestGetBuiltinToolMetas:
    def test_returns_dict(self):
        """get_builtin_tool_metas 应返回字典"""
        metas = get_builtin_tool_metas()
        assert isinstance(metas, dict)

    def test_meta_values_have_expected_keys(self):
        """每个工具的元数据应包含预期字段"""
        metas = get_builtin_tool_metas()
        # 如果有加载到的工具元数据，验证结构
        for tool_name, meta in metas.items():
            assert "data_source_map" in meta, f"工具 {tool_name} 缺少 data_source_map"
            assert "analyst_map" in meta, f"工具 {tool_name} 缺少 analyst_map"
            assert "module" in meta, f"工具 {tool_name} 缺少 module"
            assert isinstance(meta["data_source_map"], list)
            assert isinstance(meta["analyst_map"], list)
            assert isinstance(meta["module"], str)

    def test_meta_modules_are_from_domain_list(self):
        """元数据中的 module 字段应来自 _DOMAIN_MODULES"""
        metas = get_builtin_tool_metas()
        for tool_name, meta in metas.items():
            assert meta["module"] in _DOMAIN_MODULES, (
                f"工具 {tool_name} 的 module={meta['module']} 不在 _DOMAIN_MODULES 中"
            )
