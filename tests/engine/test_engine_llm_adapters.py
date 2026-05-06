"""测试 LLM 适配器初始化逻辑"""

import pytest
from unittest.mock import patch, MagicMock

from app.engine.llm_adapters.openai_compatible_base import (
    OpenAICompatibleBase,
    OPENAI_COMPATIBLE_PROVIDERS,
    create_openai_compatible_llm,
)


class TestOpenAICompatibleBaseInit:
    @patch("app.engine.llm_adapters.openai_compatible_base.ChatOpenAI.__init__", return_value=None)
    def test_with_explicit_api_key(self, mock_init):
        base = OpenAICompatibleBase(
            provider_name="test_provider",
            model="test-model",
            api_key_env_var="TEST_API_KEY",
            base_url="https://api.test.com/v1",
            api_key="sk-explicit-key",
        )
        assert base.provider_name == "test_provider"

    @patch("app.engine.llm_adapters.openai_compatible_base.ChatOpenAI.__init__", return_value=None)
    def test_reads_api_key_from_env(self, mock_init):
        with patch.dict("os.environ", {"TEST_ENV_KEY": "sk-env-key"}):
            base = OpenAICompatibleBase(
                provider_name="test_provider",
                model="test-model",
                api_key_env_var="TEST_ENV_KEY",
                base_url="https://api.test.com/v1",
            )
        assert base.provider_name == "test_provider"

    @patch("app.engine.llm_adapters.openai_compatible_base.ChatOpenAI.__init__", return_value=None)
    def test_raises_on_missing_api_key(self, mock_init):
        with patch.dict("os.environ", {}, clear=False):
            os_env = {}
            with patch("os.getenv", side_effect=lambda k, d=None: os_env.get(k, d)):
                with pytest.raises(ValueError, match="API密钥"):
                    OpenAICompatibleBase(
                        provider_name="test_provider",
                        model="test-model",
                        api_key_env_var="MISSING_KEY",
                        base_url="https://api.test.com/v1",
                    )

    @patch("app.engine.llm_adapters.openai_compatible_base.ChatOpenAI.__init__", return_value=None)
    def test_rejects_placeholder_api_key(self, mock_init):
        with patch.dict("os.environ", {"TEST_KEY": "your-api-key"}):
            with pytest.raises(ValueError):
                OpenAICompatibleBase(
                    provider_name="test_provider",
                    model="test-model",
                    api_key_env_var="TEST_KEY",
                    base_url="https://api.test.com/v1",
                )


class TestProvidersConfig:
    def test_all_expected_providers_registered(self):
        expected = ["deepseek", "dashscope", "qianfan", "zhipu", "custom_openai"]
        for p in expected:
            assert p in OPENAI_COMPATIBLE_PROVIDERS

    def test_each_provider_has_required_fields(self):
        for provider, info in OPENAI_COMPATIBLE_PROVIDERS.items():
            assert "adapter_class" in info, f"{provider} 缺少 adapter_class"
            assert "api_key_env" in info, f"{provider} 缺少 api_key_env"
            assert "models" in info, f"{provider} 缺少 models"
            assert len(info["models"]) > 0, f"{provider} 没有模型定义"


class TestCreateOpenAICompatibleLLM:
    @patch("app.engine.llm_adapters.openai_compatible_base.ChatOpenAI.__init__", return_value=None)
    def test_unsupported_provider_raises(self, mock_init):
        with pytest.raises(ValueError, match="不支持"):
            create_openai_compatible_llm(provider="nonexistent", model="x", api_key="test")

    @patch("app.engine.llm_adapters.openai_compatible_base.ChatOpenAI.__init__", return_value=None)
    def test_deepseek_creation(self, mock_init):
        llm = create_openai_compatible_llm(
            provider="deepseek", model="deepseek-chat", api_key="sk-test"
        )
        assert llm is not None

    @patch("app.engine.llm_adapters.openai_compatible_base.ChatOpenAI.__init__", return_value=None)
    def test_dashscope_creation(self, mock_init):
        llm = create_openai_compatible_llm(
            provider="dashscope", model="qwen-turbo", api_key="sk-test"
        )
        assert llm is not None
