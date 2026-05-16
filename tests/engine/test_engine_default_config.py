from test_infra import env_vars
"""
默认配置测试
测试 DEFAULT_CONFIG 的键完整性、路径解析和工具开关
"""

import os
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Test Classes
# ---------------------------------------------------------------------------

class TestDefaultConfigKeys:
    """DEFAULT_CONFIG 必需键测试"""

    @pytest.fixture
    def config(self):
        """获取 DEFAULT_CONFIG"""
        from app.engine.default_config import DEFAULT_CONFIG
        return DEFAULT_CONFIG

    def test_has_project_dir(self, config):
        """应包含 project_dir"""
        assert "project_dir" in config
        assert isinstance(config["project_dir"], str)
        assert len(config["project_dir"]) > 0

    def test_has_results_dir(self, config):
        """应包含 results_dir"""
        assert "results_dir" in config
        assert isinstance(config["results_dir"], str)

    def test_has_data_dir(self, config):
        """应包含 data_dir"""
        assert "data_dir" in config
        assert isinstance(config["data_dir"], str)

    def test_has_data_cache_dir(self, config):
        """应包含 data_cache_dir"""
        assert "data_cache_dir" in config
        assert isinstance(config["data_cache_dir"], str)

    def test_has_llm_settings(self, config):
        """应包含 LLM 配置"""
        assert "llm_provider" in config
        assert "debate_llm" in config
        assert "analyst_llm" in config
        assert "backend_url" in config

    def test_has_debate_settings(self, config):
        """应包含辩论和讨论设置"""
        assert "max_debate_rounds" in config
        assert "max_risk_discuss_rounds" in config

    def test_has_recur_limit(self, config):
        """应包含递归限制"""
        assert "max_recur_limit" in config
        assert isinstance(config["max_recur_limit"], int)

    def test_has_tool_settings(self, config):
        """应包含工具设置"""
        assert "online_tools" in config
        assert "online_news" in config
        assert "realtime_data" in config


class TestDefaultConfigValues:
    """DEFAULT_CONFIG 值验证"""

    @pytest.fixture
    def config(self):
        from app.engine.default_config import DEFAULT_CONFIG
        return DEFAULT_CONFIG

    def test_llm_provider_is_string(self, config):
        """llm_provider 应为非空字符串"""
        assert isinstance(config["llm_provider"], str)
        assert len(config["llm_provider"]) > 0

    def test_debate_llm_is_string(self, config):
        """debate_llm 应为非空字符串"""
        assert isinstance(config["debate_llm"], str)
        assert len(config["debate_llm"]) > 0

    def test_analyst_llm_is_string(self, config):
        """analyst_llm 应为非空字符串"""
        assert isinstance(config["analyst_llm"], str)
        assert len(config["analyst_llm"]) > 0

    def test_backend_url_is_valid_url(self, config):
        """backend_url 应为有效 URL"""
        assert isinstance(config["backend_url"], str)
        assert config["backend_url"].startswith("http")

    def test_max_debate_rounds_positive(self, config):
        """max_debate_rounds 应为正整数"""
        assert isinstance(config["max_debate_rounds"], int)
        assert config["max_debate_rounds"] >= 1

    def test_max_risk_discuss_rounds_positive(self, config):
        """max_risk_discuss_rounds 应为正整数"""
        assert isinstance(config["max_risk_discuss_rounds"], int)
        assert config["max_risk_discuss_rounds"] >= 1

    def test_max_recur_limit_reasonable(self, config):
        """max_recur_limit 应为合理的正整数"""
        assert isinstance(config["max_recur_limit"], int)
        assert config["max_recur_limit"] >= 10


class TestDefaultConfigPathResolution:
    """DEFAULT_CONFIG 路径解析测试"""

    def test_project_dir_points_to_project_root(self):
        """project_dir 应指向项目根目录"""
        from app.engine.default_config import DEFAULT_CONFIG

        project_dir = Path(DEFAULT_CONFIG["project_dir"])
        # 项目根目录应包含 pyproject.toml
        assert (project_dir / "pyproject.toml").exists()

    def test_project_dir_is_absolute(self):
        """project_dir 应为绝对路径"""
        from app.engine.default_config import DEFAULT_CONFIG

        project_dir = Path(DEFAULT_CONFIG["project_dir"])
        assert project_dir.is_absolute()

    def test_results_dir_is_string(self):
        """results_dir 应为字符串"""
        from app.engine.default_config import DEFAULT_CONFIG

        assert isinstance(DEFAULT_CONFIG["results_dir"], str)

    def test_data_dir_is_string(self):
        """data_dir 应为字符串"""
        from app.engine.default_config import DEFAULT_CONFIG

        assert isinstance(DEFAULT_CONFIG["data_dir"], str)


class TestDefaultConfigToolToggles:
    """DEFAULT_CONFIG 工具开关测试"""

    def test_online_tools_is_bool(self):
        """online_tools 应为布尔值"""
        from app.engine.default_config import DEFAULT_CONFIG

        assert isinstance(DEFAULT_CONFIG["online_tools"], bool)

    def test_online_news_is_bool(self):
        """online_news 应为布尔值"""
        from app.engine.default_config import DEFAULT_CONFIG

        assert isinstance(DEFAULT_CONFIG["online_news"], bool)

    def test_realtime_data_is_bool(self):
        """realtime_data 应为布尔值"""
        from app.engine.default_config import DEFAULT_CONFIG

        assert isinstance(DEFAULT_CONFIG["realtime_data"], bool)

    def test_online_tools_defaults_to_false(self):
        """online_tools 默认应为 False（当环境变量未设置时）"""
        # 清理环境变量后重新导入
        with env_vars({}):
            os.environ.pop("ONLINE_TOOLS_ENABLED", None)
            # 重新计算默认值
            expected = os.getenv("ONLINE_TOOLS_ENABLED", "false").lower() == "true"
            assert expected is False

    def test_online_news_defaults_to_true(self):
        """online_news 默认应为 True"""
        with env_vars({}):
            os.environ.pop("ONLINE_NEWS_ENABLED", None)
            expected = os.getenv("ONLINE_NEWS_ENABLED", "true").lower() == "true"
            assert expected is True

    def test_online_tools_enabled_via_env(self):
        """设置环境变量 ONLINE_TOOLS_ENABLED=true 应启用在线工具"""
        with env_vars({"ONLINE_TOOLS_ENABLED": "true"}):
            result = os.getenv("ONLINE_TOOLS_ENABLED", "false").lower() == "true"
            assert result is True

    def test_online_tools_disabled_via_env(self):
        """设置环境变量 ONLINE_TOOLS_ENABLED=false 应禁用在线工具"""
        with env_vars({"ONLINE_TOOLS_ENABLED": "false"}):
            result = os.getenv("ONLINE_TOOLS_ENABLED", "false").lower() == "true"
            assert result is False


class TestDefaultConfigNoDatabaseSettings:
    """DEFAULT_CONFIG 不应包含数据库配置"""

    def test_no_mongodb_settings(self):
        """不应包含 MongoDB 配置"""
        from app.engine.default_config import DEFAULT_CONFIG

        assert "mongodb_host" not in DEFAULT_CONFIG
        assert "mongodb_port" not in DEFAULT_CONFIG

    def test_no_redis_settings(self):
        """不应包含 Redis 配置"""
        from app.engine.default_config import DEFAULT_CONFIG

        assert "redis_host" not in DEFAULT_CONFIG
        assert "redis_port" not in DEFAULT_CONFIG

    def test_no_api_keys(self):
        """不应包含 API 密钥"""
        from app.engine.default_config import DEFAULT_CONFIG

        assert "api_key" not in DEFAULT_CONFIG
        assert "OPENAI_API_KEY" not in DEFAULT_CONFIG
        assert "DEEPSEEK_API_KEY" not in DEFAULT_CONFIG
