"""测试 TradingGraph LLM provider 路由"""

import pytest
from unittest.mock import patch, MagicMock

from app.engine.graph.trading_graph import create_llm_by_provider


class TestCreateLlmByProvider:
    def _base_kwargs(self, **overrides):
        defaults = {
            "provider": "openai",
            "model": "gpt-4",
            "backend_url": "https://api.openai.com/v1",
            "temperature": 0.7,
            "max_tokens": 4000,
            "timeout": 60,
            "api_key": "sk-test-key",
        }
        defaults.update(overrides)
        return defaults

    @patch("app.engine.graph.trading_graph.ChatOpenAI")
    def test_openai_provider(self, mock_cls):
        mock_cls.return_value = MagicMock()
        result = create_llm_by_provider(**self._base_kwargs(provider="openai"))
        mock_cls.assert_called_once()

    @patch("app.engine.llm_adapters.deepseek_adapter.ChatDeepSeek")
    def test_deepseek_provider(self, mock_cls):
        mock_cls.return_value = MagicMock()
        result = create_llm_by_provider(**self._base_kwargs(provider="deepseek"))
        assert result is not None

    @patch("app.engine.llm_adapters.dashscope_openai_adapter.ChatDashScopeOpenAI")
    def test_dashscope_provider(self, mock_cls):
        mock_cls.return_value = MagicMock()
        result = create_llm_by_provider(**self._base_kwargs(provider="dashscope"))
        assert result is not None

    @patch("app.engine.graph.trading_graph.ChatAnthropic")
    def test_anthropic_provider(self, mock_cls):
        mock_cls.return_value = MagicMock()
        result = create_llm_by_provider(**self._base_kwargs(provider="anthropic"))
        mock_cls.assert_called_once()

    @patch("app.engine.llm_adapters.google_openai_adapter.ChatGoogleOpenAI")
    def test_google_provider(self, mock_cls):
        mock_cls.return_value = MagicMock()
        with patch.dict("os.environ", {"GOOGLE_API_KEY": "test-google-key"}):
            result = create_llm_by_provider(**self._base_kwargs(provider="google"))
        assert result is not None

    @patch("app.engine.graph.trading_graph.ChatOpenAI")
    def test_unknown_provider_falls_back_to_openai(self, mock_cls):
        mock_cls.return_value = MagicMock()
        result = create_llm_by_provider(**self._base_kwargs(provider="unknown_provider"))
        mock_cls.assert_called_once()

    @patch("app.engine.graph.trading_graph.ChatOpenAI")
    def test_passes_model_and_temperature(self, mock_cls):
        mock_cls.return_value = MagicMock()
        create_llm_by_provider(**self._base_kwargs(model="gpt-4o", temperature=0.3))
        assert mock_cls.call_args is not None
        call_kwargs = mock_cls.call_args[1]
        assert call_kwargs.get("model_name") == "gpt-4o" or call_kwargs.get("model") == "gpt-4o"
        assert call_kwargs.get("temperature") == 0.3

    def test_returns_llm_instance(self):
        with patch("app.engine.graph.trading_graph.ChatOpenAI") as mock_cls:
            mock_instance = MagicMock()
            mock_cls.return_value = mock_instance
            result = create_llm_by_provider(**self._base_kwargs(provider="openai"))
            assert result is mock_instance
