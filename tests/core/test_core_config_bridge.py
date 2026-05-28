"""测试配置桥接模块"""

import os
import pytest

from test_infra import env_vars
from app.core.config_bridge import (
    get_bridged_model,
    clear_bridged_config,
)


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

