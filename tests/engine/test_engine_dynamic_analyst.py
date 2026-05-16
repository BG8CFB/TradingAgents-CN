"""测试 DynamicAnalystFactory 完整方法

使用真实配置文件（临时 YAML）替代 patch，
验证工厂方法的查找、映射和进度功能。
"""

import os
import pytest

from app.engine.agents.analysts.dynamic_analyst import DynamicAnalystFactory


@pytest.fixture
def sample_config(tmp_path):
    """创建临时配置文件并返回路径"""
    import yaml
    config = {
        "customModes": [
            {
                "slug": "market-analyst",
                "name": "市场技术分析师",
                "roleDefinition": "分析市场技术指标",
                "tools": ["get_stock_data", "get_stock_fundamentals"],
            },
            {
                "slug": "news-analyst",
                "name": "新闻分析师",
                "roleDefinition": "分析新闻舆情",
                "tools": ["get_stock_news"],
            },
        ],
        "agents": [
            {
                "slug": "fundamentals-analyst",
                "name": "基本面分析师",
                "roleDefinition": "分析基本面数据",
                "tools": ["get_stock_fundamentals"],
            },
        ],
    }
    config_path = tmp_path / "phase1_agents_config.yaml"
    with open(config_path, "w", encoding="utf-8") as f:
        yaml.dump(config, f, allow_unicode=True)
    return str(config_path)


class TestBuildLookupMap:
    def test_map_contains_slug_key(self, sample_config):
        lookup = DynamicAnalystFactory.build_lookup_map(sample_config)
        assert "market-analyst" in lookup

    def test_map_contains_internal_key(self, sample_config):
        lookup = DynamicAnalystFactory.build_lookup_map(sample_config)
        assert "market" in lookup

    def test_map_contains_name_key(self, sample_config):
        lookup = DynamicAnalystFactory.build_lookup_map(sample_config)
        assert "市场技术分析师" in lookup

    def test_all_agents_have_lookup_entries(self, sample_config):
        lookup = DynamicAnalystFactory.build_lookup_map(sample_config)
        assert "news-analyst" in lookup
        assert "fundamentals-analyst" in lookup


class TestBuildNodeMapping:
    def test_mapping_has_analyst_entries(self, sample_config):
        mapping = DynamicAnalystFactory.build_node_mapping(sample_config)
        assert len(mapping) > 0

    def test_analyst_mapping_values_are_display_names(self, sample_config):
        mapping = DynamicAnalystFactory.build_node_mapping(sample_config)
        for key, display_name in mapping.items():
            if display_name is None:
                continue
            assert isinstance(display_name, str)
            assert len(display_name) > 0

    def test_tool_nodes_have_none_mapping(self, sample_config):
        mapping = DynamicAnalystFactory.build_node_mapping(sample_config)
        none_keys = [k for k, v in mapping.items() if v is None]
        assert len(none_keys) > 0


class TestBuildProgressMap:
    def test_dynamic_analyst_progress(self, sample_config):
        pm = DynamicAnalystFactory.build_progress_map(config_path=sample_config)
        has_analyst = any("分析师" in k for k in pm.keys())
        assert has_analyst

    def test_progress_includes_all_fixed_stages(self, sample_config):
        pm = DynamicAnalystFactory.build_progress_map(config_path=sample_config)
        assert "🐂 看涨研究员" in pm
        assert "🐻 看跌研究员" in pm
        assert "📊 生成报告" in pm


class TestInferToolKey:
    def test_market_slug(self):
        result = DynamicAnalystFactory._infer_tool_key("market-analyst", "市场分析师")
        assert isinstance(result, str)

    def test_news_slug(self):
        result = DynamicAnalystFactory._infer_tool_key("news-analyst", "新闻分析师")
        assert isinstance(result, str)


class TestWrapToolSafe:
    def test_wrapped_tool_preserves_name(self):
        """本地工具（无 server_name）应直接返回不包装"""
        from langchain_core.tools import tool as lc_tool

        @lc_tool
        def test_tool(x: str) -> str:
            """测试工具"""
            return x

        wrapped = DynamicAnalystFactory._wrap_tool_safe(test_tool, None)
        assert wrapped is not None
        assert wrapped.name == "test_tool"

    def test_wrapped_tool_with_toolkit(self):
        """传入 toolkit（但非外部 MCP 工具）应直接返回"""
        from langchain_core.tools import tool as lc_tool

        @lc_tool
        def test_tool(x: str) -> str:
            """测试工具"""
            return x

        toolkit = {"task_mcp_manager": None}
        wrapped = DynamicAnalystFactory._wrap_tool_safe(test_tool, toolkit)
        assert wrapped is not None


class TestClearCache:
    def test_clear_cache_no_error(self):
        DynamicAnalystFactory.clear_cache()

    def test_load_after_clear(self, sample_config):
        DynamicAnalystFactory.clear_cache()
        result = DynamicAnalystFactory.load_config(sample_config)
        assert "customModes" in result
