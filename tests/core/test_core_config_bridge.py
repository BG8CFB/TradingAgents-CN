"""测试配置桥接模块"""

import os
import pytest

from test_infra import env_vars
from app.core.config_bridge import (
    get_bridged_api_key,
    get_bridged_model,
    clear_bridged_config,
)


class TestGetBridgedApiKey:
    def test_reads_from_env(self):
        with env_vars({"DEEPSEEK_API_KEY": "sk-test-key"}):
            result = get_bridged_api_key("deepseek")
            assert result == "sk-test-key"

    def test_case_insensitive_provider(self):
        with env_vars({"GOOGLE_API_KEY": "test-google-key"}):
            result = get_bridged_api_key("Google")
            assert result == "test-google-key"

    def test_returns_none_for_missing(self):
        os.environ.pop("NONEXISTENT_API_KEY", None)
        result = get_bridged_api_key("nonexistent")
        assert result is None


class TestGetBridgedModel:
    def test_default_model(self):
        with env_vars({"TRADINGAGENTS_DEFAULT_MODEL": "qwen-max"}):
            result = get_bridged_model("default")
            assert result == "qwen-max"

    def test_analyst_model(self):
        with env_vars({"TRADINGAGENTS_ANALYST_MODEL": "qwen-turbo"}):
            result = get_bridged_model("analyst")
            assert result == "qwen-turbo"

    def test_debate_model(self):
        with env_vars({"TRADINGAGENTS_DEBATE_MODEL": "qwen-max"}):
            result = get_bridged_model("debate")
            assert result == "qwen-max"

    def test_unknown_type_returns_default(self):
        with env_vars({"TRADINGAGENTS_DEFAULT_MODEL": "qwen-plus"}):
            result = get_bridged_model("unknown")
            assert result == "qwen-plus"

    def test_returns_none_when_not_set(self):
        os.environ.pop("TRADINGAGENTS_DEFAULT_MODEL", None)
        result = get_bridged_model("default")
        assert result is None


class TestClearBridgedConfig:
    def test_clears_model_env_vars(self):
        with env_vars({
            "TRADINGAGENTS_DEFAULT_MODEL": "test",
            "TRADINGAGENTS_ANALYST_MODEL": "test",
            "TRADINGAGENTS_DEBATE_MODEL": "test",
        }):
            clear_bridged_config()
            assert "TRADINGAGENTS_DEFAULT_MODEL" not in os.environ
            assert "TRADINGAGENTS_ANALYST_MODEL" not in os.environ
            assert "TRADINGAGENTS_DEBATE_MODEL" not in os.environ

    def test_clears_provider_api_keys(self):
        with env_vars({
            "OPENAI_API_KEY": "test",
            "DEEPSEEK_API_KEY": "test",
            "GOOGLE_API_KEY": "test",
        }):
            clear_bridged_config()
            assert "OPENAI_API_KEY" not in os.environ
            assert "DEEPSEEK_API_KEY" not in os.environ
            assert "GOOGLE_API_KEY" not in os.environ

    def test_clears_datasource_keys(self):
        with env_vars({
            "TUSHARE_TOKEN": "test",
            "FINNHUB_API_KEY": "test",
        }):
            clear_bridged_config()
            assert "TUSHARE_TOKEN" not in os.environ
            assert "FINNHUB_API_KEY" not in os.environ
