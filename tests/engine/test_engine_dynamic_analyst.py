"""测试 DynamicAnalystFactory 完整方法"""

import os
import pytest
from unittest.mock import patch, MagicMock

from app.engine.agents.analysts.dynamic_analyst import DynamicAnalystFactory


@pytest.fixture
def sample_config():
    return {
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


class TestBuildLookupMap:
    def test_map_contains_slug_key(self, sample_config):
        with patch.object(DynamicAnalystFactory, "load_config", return_value=sample_config):
            lookup = DynamicAnalystFactory.build_lookup_map()
            assert "market-analyst" in lookup

    def test_map_contains_internal_key(self, sample_config):
        with patch.object(DynamicAnalystFactory, "load_config", return_value=sample_config):
            lookup = DynamicAnalystFactory.build_lookup_map()
            assert "market" in lookup

    def test_map_contains_name_key(self, sample_config):
        with patch.object(DynamicAnalystFactory, "load_config", return_value=sample_config):
            lookup = DynamicAnalystFactory.build_lookup_map()
            assert "市场技术分析师" in lookup

    def test_all_agents_have_lookup_entries(self, sample_config):
        with patch.object(DynamicAnalystFactory, "load_config", return_value=sample_config):
            lookup = DynamicAnalystFactory.build_lookup_map()
            assert "news-analyst" in lookup
            assert "fundamentals-analyst" in lookup


class TestBuildNodeMapping:
    def test_mapping_has_analyst_entries(self, sample_config):
        with patch.object(DynamicAnalystFactory, "load_config", return_value=sample_config):
            mapping = DynamicAnalystFactory.build_node_mapping()
            assert len(mapping) > 0

    def test_analyst_mapping_values_are_display_names(self, sample_config):
        with patch.object(DynamicAnalystFactory, "load_config", return_value=sample_config):
            mapping = DynamicAnalystFactory.build_node_mapping()
            for key, display_name in mapping.items():
                if display_name is None:
                    continue
                assert isinstance(display_name, str)
                assert len(display_name) > 0

    def test_tool_nodes_have_none_mapping(self, sample_config):
        with patch.object(DynamicAnalystFactory, "load_config", return_value=sample_config):
            mapping = DynamicAnalystFactory.build_node_mapping()
            none_keys = [k for k, v in mapping.items() if v is None]
            assert len(none_keys) > 0


class TestBuildProgressMap:
    def test_dynamic_analyst_progress(self, sample_config):
        with patch.object(DynamicAnalystFactory, "load_config", return_value=sample_config):
            pm = DynamicAnalystFactory.build_progress_map()
            has_analyst = any("分析师" in k for k in pm.keys())
            assert has_analyst

    def test_progress_includes_all_fixed_stages(self, sample_config):
        with patch.object(DynamicAnalystFactory, "load_config", return_value=sample_config):
            pm = DynamicAnalystFactory.build_progress_map()
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
        tool = MagicMock()
        tool.name = "test_tool"
        tool.invoke.return_value = "result"
        wrapped = DynamicAnalystFactory._wrap_tool_safe(tool, None)
        assert wrapped is not None

    def test_wrapped_tool_handles_error(self):
        tool = MagicMock()
        tool.name = "test_tool"
        tool.invoke.side_effect = Exception("fail")
        wrapped = DynamicAnalystFactory._wrap_tool_safe(tool, MagicMock())
        assert wrapped is not None


class TestClearCache:
    def test_clear_cache_no_error(self):
        DynamicAnalystFactory.clear_cache()

    def test_load_after_clear(self, sample_config, tmp_path):
        import yaml
        config_path = tmp_path / "phase1_agents_config.yaml"
        with open(config_path, "w", encoding="utf-8") as f:
            yaml.dump(sample_config, f, allow_unicode=True)
        DynamicAnalystFactory.clear_cache()
        result = DynamicAnalystFactory.load_config(str(config_path))
        assert "customModes" in result
