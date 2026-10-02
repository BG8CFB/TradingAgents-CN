"""测试 DynamicAnalystFactory 完整方法

配置源已 DB 化（agent_specs 集合，2026-09 工作流通用化）：fixture 经 store
真实写入测试条目（替代旧临时 YAML 注入），验证工厂方法的查找、映射和进度功能。
"""

import pytest

from app.engine.agents.analysts.dynamic_analyst import DynamicAnalystFactory

pytestmark = pytest.mark.requires_db


@pytest.fixture
def sample_config(mongodb_available):
    """向 agent_specs(phase=1) 注入测试条目；返回 None（config_path 参数已无效果，仅签名兼容）"""
    from app.engine.orchestrator.registry import clear_registry_cache
    from app.engine.orchestrator.workflow import store

    # registry 身份表进程内固化（首次查询后缓存）：注入前失效，确保本 fixture 读到测试条目
    clear_registry_cache()
    entries = [
        {
            "slug": "market-analyst",
            "name": "市场技术分析师",
            "roleDefinition": "分析市场技术指标",
            "data_tools": ["daily_quotes"],
        },
        {"slug": "news-analyst", "name": "新闻分析师", "roleDefinition": "分析新闻舆情"},
        {"slug": "fundamentals-analyst", "name": "基本面分析师", "roleDefinition": "分析基本面数据"},
    ]
    store.replace_phase_agent_specs(1, entries)
    yield None
    # 清整个集合（非仅 phase1）：store 降级判据是「集合整空」——只清单 phase 会留下
    # 「phase1 空、集合非空」状态导致降级不触发、其他用例读到空分析师库
    store._db()[store.AGENT_SPECS_COLLECTION].delete_many({})
    store.invalidate_store_cache()
    # 注入期间触发的查询会把测试条目固化进 registry 进程缓存（_identities_cache /
    # _slug_name_cache），只清 DB+store 缓存会让后续 registry 测试读到污染数据
    clear_registry_cache()


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


class TestInferToolKey:
    def test_market_slug(self):
        result = DynamicAnalystFactory._infer_tool_key("market-analyst", "市场分析师")
        assert isinstance(result, str)

    def test_news_slug(self):
        result = DynamicAnalystFactory._infer_tool_key("news-analyst", "新闻分析师")
        assert isinstance(result, str)


class TestClearCache:
    def test_clear_cache_no_error(self):
        DynamicAnalystFactory.clear_cache()

    def test_load_after_clear(self, sample_config):
        DynamicAnalystFactory.clear_cache()
        result = DynamicAnalystFactory.load_config(sample_config)
        assert "customModes" in result
