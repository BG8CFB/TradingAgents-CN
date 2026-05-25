"""
测试统一 LLM 工厂函数 create_llm 的 provider 路由

直接调用 create_llm 真实函数，验证返回正确的适配器类型
"""

import os
import pytest

os.environ.pop("SSL_CERT_FILE", None)

from app.engine.llm_adapters.factory import create_llm, PROVIDER_DEFAULTS
from app.engine.llm_adapters.openai_compatible import OpenAICompatibleAdapter
from app.engine.llm_adapters.anthropic_adapter import AnthropicAdapter
from app.engine.llm_adapters.google_native import GoogleNativeAdapter
from app.constants.llm_defaults import DEFAULT_MAX_TOKENS, DEFAULT_TEMPERATURE, DEFAULT_TIMEOUT


class TestCreateLlm:
    def _base_kwargs(self, **overrides):
        defaults = {
            "provider": "openai",
            "model": "gpt-4",
            "base_url": "https://api.openai.com/v1",
            "temperature": DEFAULT_TEMPERATURE,
            "max_tokens": DEFAULT_MAX_TOKENS,
            "timeout": DEFAULT_TIMEOUT,
            "api_key": "sk-test-key",
        }
        defaults.update(overrides)
        return defaults

    def test_openai_provider_returns_openai_compatible(self):
        llm = create_llm(**self._base_kwargs(provider="openai"))
        assert isinstance(llm, OpenAICompatibleAdapter)

    def test_deepseek_provider_returns_openai_compatible(self):
        llm = create_llm(**self._base_kwargs(provider="deepseek", model="deepseek-chat"))
        assert isinstance(llm, OpenAICompatibleAdapter)

    def test_dashscope_provider_returns_openai_compatible(self):
        llm = create_llm(**self._base_kwargs(provider="dashscope", model="qwen-turbo"))
        assert isinstance(llm, OpenAICompatibleAdapter)

    def test_zhipu_provider_returns_openai_compatible(self):
        llm = create_llm(**self._base_kwargs(provider="zhipu", model="glm-4"))
        assert isinstance(llm, OpenAICompatibleAdapter)

    def test_anthropic_provider_returns_anthropic_adapter(self):
        llm = create_llm(**self._base_kwargs(provider="anthropic", model="claude-sonnet-4-20250514"))
        assert isinstance(llm, AnthropicAdapter)

    def test_google_provider_returns_google_native(self):
        llm = create_llm(**self._base_kwargs(provider="google", model="gemini-2.0-flash"))
        assert isinstance(llm, GoogleNativeAdapter)

    def test_unknown_provider_defaults_to_openai_compatible(self):
        llm = create_llm(**self._base_kwargs(provider="some_unknown_provider"))
        assert isinstance(llm, OpenAICompatibleAdapter)

    def test_ollama_provider_allows_no_api_key(self):
        llm = create_llm(
            provider="ollama",
            model="qwen2:7b",
            base_url="http://localhost:11434/v1",
            api_key="ollama",
        )
        assert isinstance(llm, OpenAICompatibleAdapter)

    def test_dashscope_url_normalization(self):
        llm = create_llm(
            **self._base_kwargs(
                provider="dashscope",
                model="qwen-turbo",
                base_url="https://dashscope.aliyuncs.com/api/v1",
            )
        )
        actual_url = llm.openai_api_base
        assert "compatible-mode" in actual_url

    def test_provider_defaults_registry_completeness(self):
        required_providers = ["openai", "deepseek", "dashscope", "zhipu", "qianfan",
                              "anthropic", "google", "ollama", "siliconflow", "openrouter"]
        for p in required_providers:
            assert p in PROVIDER_DEFAULTS, f"{p} 未在 PROVIDER_DEFAULTS 中注册"

    def test_provider_defaults_have_protocol(self):
        for name, cfg in PROVIDER_DEFAULTS.items():
            assert "protocol" in cfg, f"{name} 缺少 protocol 字段"
            assert cfg["protocol"] in ("openai", "anthropic", "google")

    def test_openai_compatible_has_provider_name(self):
        llm = create_llm(**self._base_kwargs(provider="deepseek", model="deepseek-chat"))
        assert llm.provider_name == "deepseek"

    def test_factory_sets_model_name(self):
        llm = create_llm(**self._base_kwargs(provider="openai", model="gpt-4o"))
        assert llm.model_name == "gpt-4o"
