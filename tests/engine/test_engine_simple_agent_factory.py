"""测试 SimpleAgentFactory 工厂模块

使用真实的 YAML 配置文件替代 patch/mock，
验证配置加载、智能体查找、进度映射和图标推断。
"""

import os
import pytest

from app.engine.agents.analysts.simple_agent_factory import SimpleAgentFactory


class TestLoadConfig:
    def test_loads_from_explicit_path(self, sample_yaml_config):
        config = SimpleAgentFactory.load_config(sample_yaml_config)
        assert "customModes" in config
        assert len(config["customModes"]) == 2

    def test_returns_empty_for_missing_file(self):
        config = SimpleAgentFactory.load_config("/nonexistent/path/config.yaml")
        assert config == {}

    def test_env_var_takes_priority(self, sample_yaml_config):
        config_dir = os.path.dirname(sample_yaml_config)
        original = os.environ.get("AGENT_CONFIG_DIR")
        try:
            os.environ["AGENT_CONFIG_DIR"] = config_dir
            config = SimpleAgentFactory.load_config()
            assert "customModes" in config
        finally:
            if original is not None:
                os.environ["AGENT_CONFIG_DIR"] = original
            else:
                os.environ.pop("AGENT_CONFIG_DIR", None)


class TestGetAgentConfig:
    def test_find_by_slug(self, sample_yaml_config):
        agent = SimpleAgentFactory.get_agent_config("market-analyst", sample_yaml_config)
        assert agent is not None
        assert agent["slug"] == "market-analyst"

    def test_find_by_internal_key(self, sample_yaml_config):
        agent = SimpleAgentFactory.get_agent_config("market", sample_yaml_config)
        assert agent is not None
        assert agent["slug"] == "market-analyst"

    def test_find_by_chinese_name(self, sample_yaml_config):
        agent = SimpleAgentFactory.get_agent_config("新闻分析师", sample_yaml_config)
        assert agent is not None
        assert agent["slug"] == "news-analyst"

    def test_returns_none_for_unknown(self, sample_yaml_config):
        agent = SimpleAgentFactory.get_agent_config("nonexistent-agent", sample_yaml_config)
        assert agent is None


class TestGetAllAgents:
    def test_merges_custom_modes_and_agents(self, sample_yaml_config):
        agents = SimpleAgentFactory.get_all_agents(sample_yaml_config)
        assert len(agents) == 3  # 2 customModes + 1 agents

    def test_returns_empty_list_for_empty_config(self, tmp_path):
        """空配置文件应返回空列表"""
        import yaml
        config_path = tmp_path / "phase1_agents_config.yaml"
        with open(config_path, "w", encoding="utf-8") as f:
            yaml.dump({}, f)

        agents = SimpleAgentFactory.get_all_agents(str(config_path))
        assert agents == []


class TestBuildProgressMap:
    def test_map_contains_fixed_entries(self, sample_yaml_config):
        pm = SimpleAgentFactory.build_progress_map(config_path=sample_yaml_config)
        assert "🐂 看涨研究员" in pm
        assert "🐻 看跌研究员" in pm
        assert "👔 研究经理" in pm
        assert "📊 生成报告" in pm

    def test_progress_values_increase(self, sample_yaml_config):
        pm = SimpleAgentFactory.build_progress_map(config_path=sample_yaml_config)
        fixed_keys = ["🐂 看涨研究员", "🐻 看跌研究员", "👔 研究经理",
                       "💼 交易员决策", "🎯 风险经理", "📊 生成报告"]
        values = [pm[k] for k in fixed_keys if k in pm]
        for i in range(len(values) - 1):
            assert values[i] < values[i + 1]


class TestGetAnalystIcon:
    def test_news_icon(self):
        assert SimpleAgentFactory._get_analyst_icon("news-analyst") == "📰"

    def test_social_icon(self):
        assert SimpleAgentFactory._get_analyst_icon("social-analyst") == "💬"

    def test_fundamental_icon(self):
        assert SimpleAgentFactory._get_analyst_icon("fundamentals-analyst") == "💼"

    def test_china_icon(self):
        assert SimpleAgentFactory._get_analyst_icon("china-analyst") == "🇨🇳"

    def test_capital_icon(self):
        assert SimpleAgentFactory._get_analyst_icon("capital-analyst") == "💸"

    def test_market_icon(self):
        assert SimpleAgentFactory._get_analyst_icon("market-analyst") == "📊"

    def test_default_icon(self):
        assert SimpleAgentFactory._get_analyst_icon("custom-analyst") == "🤖"

    def test_name_based_icon(self):
        assert SimpleAgentFactory._get_analyst_icon("x", "新闻分析") == "📰"
        assert SimpleAgentFactory._get_analyst_icon("x", "基本面分析") == "💼"
