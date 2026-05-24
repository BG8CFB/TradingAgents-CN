"""测试 builtin/loader 工具加载器

调用真实的 load_builtin_tools 和 get_builtin_tool_specs 函数，
验证内置工具模块的加载行为。
"""

import pytest

from app.engine.tools.builtin.loader import load_builtin_tools, get_builtin_tool_specs
from app.engine.tools.builtin.registry import BUILTIN_TOOL_REGISTRY


class TestBuiltinToolRegistry:
    def test_registry_not_empty(self):
        """注册表不应为空"""
        assert len(BUILTIN_TOOL_REGISTRY) > 0

    def test_expected_tool_ids_present(self):
        """应包含所有预期的工具 ID"""
        tool_ids = {spec.tool_id for spec in BUILTIN_TOOL_REGISTRY}
        expected = [
            "daily_quotes", "intraday_quotes", "market_quotes",
            "financial_data", "fundamentals", "news", "sentiment",
            "china_market", "dragon_tiger", "block_trade",
            "money_flow", "margin_trade", "daily_indicators", "basic_info",
        ]
        for tid in expected:
            assert tid in tool_ids, f"缺少工具: {tid}"

    def test_each_spec_has_required_fields(self):
        """每个 BuiltinToolSpec 应有必填字段"""
        for spec in BUILTIN_TOOL_REGISTRY:
            assert spec.tool_id, "tool_id 不应为空"
            assert spec.display_name, "display_name 不应为空"
            assert isinstance(spec.domains, list), "domains 应为列表"
            assert isinstance(spec.markets, list), "markets 应为列表"
            assert callable(spec.fn), "fn 应为可调用对象"
            assert isinstance(spec.inject_args, dict), "inject_args 应为字典"
            assert spec.description, "description 不应为空"


class TestLoadBuiltinTools:
    def test_returns_list(self):
        """load_builtin_tools 应返回列表"""
        result = load_builtin_tools()
        assert isinstance(result, list)

    def test_tool_items_have_name(self):
        """加载的工具对象应具有 name 属性"""
        result = load_builtin_tools()
        for tool in result:
            assert hasattr(tool, "name")
            assert isinstance(tool.name, str)


class TestGetBuiltinToolSpecs:
    def test_returns_list(self):
        """get_builtin_tool_specs 应返回列表"""
        specs = get_builtin_tool_specs()
        assert isinstance(specs, list)

    def test_specs_match_registry(self):
        """返回的规格应与注册表一致"""
        specs = get_builtin_tool_specs()
        assert len(specs) == len(BUILTIN_TOOL_REGISTRY)
