"""测试 LLM 适配器：OpenAICompatibleAdapter、BaseChatAdapter、factory"""

import os
import pytest

from app.engine.llm_adapters.factory import create_llm, PROVIDER_DEFAULTS
from app.engine.llm_adapters.openai_compatible import OpenAICompatibleAdapter
from app.engine.llm_adapters.base import BaseChatAdapter
from test_infra import env_vars


class TestBaseChatAdapterResolveApiKey:
    """测试 API Key 解析逻辑

    Phase 5 重构后：resolve_api_key 仅接受显式 api_key 参数，
    不再从环境变量读取（API Key 通过数据库管理）。
    """

    def test_explicit_api_key_takes_priority(self):
        key = BaseChatAdapter.resolve_api_key("test", api_key="sk-explicit", api_key_env="TEST_KEY")
        assert key == "sk-explicit"

    def test_returns_none_when_no_explicit_key(self):
        key = BaseChatAdapter.resolve_api_key("test", api_key=None, api_key_env="TEST_KEY")
        assert key is None

    def test_returns_none_when_no_env_var(self):
        key = BaseChatAdapter.resolve_api_key("test", api_key=None, api_key_env=None)
        assert key is None

    def test_rejects_placeholder_api_key(self):
        key = BaseChatAdapter.resolve_api_key("test", api_key="your-api-key", api_key_env=None)
        assert key is None

    def test_ignores_env_var_fallback(self):
        """确认不再从环境变量读取 API Key"""
        with env_vars({"TEST_ENV_KEY": "sk-env-value"}):
            key = BaseChatAdapter.resolve_api_key("test", api_key=None, api_key_env="TEST_ENV_KEY")
            assert key is None


class TestOpenAICompatibleAdapterInit:
    """测试 OpenAICompatibleAdapter 初始化"""

    def test_creates_with_explicit_api_key(self):
        llm = OpenAICompatibleAdapter(
            provider="openai",
            model="gpt-4",
            api_key="sk-test",
            base_url="https://api.openai.com/v1",
        )
        assert llm.provider_name == "openai"

    def test_creates_deepseek_adapter(self):
        llm = create_llm(provider="deepseek", model="deepseek-chat", api_key="sk-test")
        assert isinstance(llm, OpenAICompatibleAdapter)
        assert llm.provider_name == "deepseek"

    def test_creates_dashscope_adapter(self):
        llm = create_llm(provider="dashscope", model="qwen-turbo", api_key="sk-test")
        assert isinstance(llm, OpenAICompatibleAdapter)
        assert llm.provider_name == "dashscope"

    def test_raises_on_missing_api_key(self):
        with pytest.raises(ValueError, match="API 密钥"):
            OpenAICompatibleAdapter(
                provider="openai",
                model="gpt-4",
                base_url="https://api.openai.com/v1",
            )

    def test_ollama_allows_no_key(self):
        llm = OpenAICompatibleAdapter(
            provider="ollama",
            model="qwen2:7b",
            base_url="http://localhost:11434/v1",
            api_key="ollama",
        )
        assert llm.provider_name == "ollama"


class TestProviderDefaultsRegistry:
    """测试 PROVIDER_DEFAULTS 注册表"""

    def test_all_expected_providers_registered(self):
        expected = [
            "openai", "deepseek", "dashscope", "zhipu", "qianfan",
            "siliconflow", "openrouter", "ollama", "anthropic", "google",
        ]
        for p in expected:
            assert p in PROVIDER_DEFAULTS, f"{p} 未在 PROVIDER_DEFAULTS 中注册"

    def test_each_provider_has_required_fields(self):
        for name, cfg in PROVIDER_DEFAULTS.items():
            assert "protocol" in cfg, f"{name} 缺少 protocol 字段"
            assert cfg["protocol"] in ("openai", "anthropic", "google")

    def test_no_api_key_env_in_defaults(self):
        """Phase 5 重构后：PROVIDER_DEFAULTS 不再包含 api_key_env（API Key 从数据库读取）"""
        for name, cfg in PROVIDER_DEFAULTS.items():
            assert "api_key_env" not in cfg, f"{name} 不应包含 api_key_env 字段"
