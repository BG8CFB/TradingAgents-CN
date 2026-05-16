from test_infra import env_vars
from test_infra import env_vars
"""测试统一配置管理"""

import json
import os
import pytest
from pathlib import Path

from app.core.unified_config import UnifiedConfigManager


@pytest.fixture
def manager(tmp_path):
    m = UnifiedConfigManager()
    m._config_dir = tmp_path
    m._models_file = tmp_path / "models.json"
    m._settings_file = tmp_path / "settings.json"
    return m


class TestLoadJson:
    def test_returns_dict_for_valid_file(self, manager, tmp_path):
        test_file = tmp_path / "test.json"
        test_file.write_text('{"key": "value"}', encoding="utf-8")
        result = manager._load_json(test_file)
        assert result == {"key": "value"}

    def test_returns_empty_for_missing_file(self, manager):
        result = manager._load_json(Path("/nonexistent/file.json"))
        assert result == {}

    def test_returns_empty_for_invalid_json(self, manager, tmp_path):
        test_file = tmp_path / "bad.json"
        test_file.write_text("not json", encoding="utf-8")
        result = manager._load_json(test_file)
        assert result == {}


class TestSaveJson:
    def test_saves_valid_json(self, manager, tmp_path):
        target = tmp_path / "output.json"
        manager._save_json(target, {"a": 1, "b": "测试"})
        content = target.read_text(encoding="utf-8")
        assert json.loads(content) == {"a": 1, "b": "测试"}

    def test_creates_parent_directory(self, manager, tmp_path):
        target = tmp_path / "sub" / "dir" / "file.json"
        manager._save_json(target, {"x": 1})
        assert target.exists()


class TestGetLegacyModels:
    def test_returns_list_from_models_json(self, manager):
        manager._models_file.write_text(json.dumps([
            {"provider": "openai", "model_name": "gpt-4"},
        ]), encoding="utf-8")
        result = manager.get_legacy_models()
        assert len(result) == 1
        assert result[0]["provider"] == "openai"

    def test_returns_empty_when_no_file(self, manager):
        result = manager.get_legacy_models()
        assert result == {} or result == []


class TestGetLlmConfigs:
    def test_converts_legacy_to_llm_configs(self, manager):
        manager._models_file.write_text(json.dumps([
            {"provider": "deepseek", "model_name": "deepseek-chat", "base_url": "https://api.deepseek.com"},
        ]), encoding="utf-8")
        result = manager.get_llm_configs()
        assert len(result) == 1
        assert result[0].model_name == "deepseek-chat"


class TestSystemSettings:
    def test_get_system_settings(self, manager):
        manager._settings_file.write_text(json.dumps({"default_model": "qwen-turbo"}), encoding="utf-8")
        result = manager.get_system_settings()
        assert result["default_model"] == "qwen-turbo"

    def test_save_system_settings_merges(self, manager):
        manager._settings_file.write_text(json.dumps({"a": 1, "b": 2}), encoding="utf-8")
        manager.save_system_settings({"b": 3, "c": 4})
        result = manager.get_system_settings()
        assert result["a"] == 1
        assert result["b"] == 3
        assert result["c"] == 4

    def test_save_clears_mcp_tool_loader(self, manager):
        manager._settings_file.write_text("{}", encoding="utf-8")
        manager.save_system_settings({"mcp_tool_loader": "something"})
        result = manager.get_system_settings()
        assert result["mcp_tool_loader"] is None


class TestModelAccessors:
    def test_get_default_model(self, manager):
        manager._settings_file.write_text(json.dumps({"quick_analysis_model": "qwen-turbo"}), encoding="utf-8")
        result = manager.get_default_model()
        assert result == "qwen-turbo"

    def test_get_default_model_fallback(self, manager):
        manager._settings_file.write_text("{}", encoding="utf-8")
        result = manager.get_default_model()
        assert result == "qwen-turbo"

    def test_get_quick_analysis_model(self, manager):
        manager._settings_file.write_text(json.dumps({"quick_analysis_model": "qwen-plus"}), encoding="utf-8")
        result = manager.get_quick_analysis_model()
        assert result == "qwen-plus"

    def test_get_deep_analysis_model(self, manager):
        manager._settings_file.write_text(json.dumps({"deep_analysis_model": "qwen-max"}), encoding="utf-8")
        result = manager.get_deep_analysis_model()
        assert result == "qwen-max"


class TestDatabaseConfigs:
    def test_returns_mongodb_and_redis(self, manager):
        from app.core.config import settings
        result = manager.get_database_configs()
        assert len(result) == 2
        types = {c.type for c in result}
        assert "mongodb" in types
        assert "redis" in types
