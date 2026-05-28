from test_infra import env_vars
"""测试 API Key 工具函数"""

import os
import pytest

from app.utils.api_key_utils import (
    is_placeholder_api_key,
    is_valid_api_key,
    truncate_api_key,
    should_skip_api_key_update,
)


class TestIsPlaceholderApiKey:
    @pytest.mark.parametrize("value", [
        "***", "******", "xxx", "xxxxxx", "sk-xxx",
        "your-api-key", "your_api_key", "your key here",
        "your-key-here", "change-me", "changeme", "test", "null", "none",
    ])
    def test_exact_placeholder_values(self, value):
        assert is_placeholder_api_key(value) is True

    @pytest.mark.parametrize("value", [
        "sk-some...truncated", "your-custom-key",
        "your_special_key", "placeholder_value",
        "replace-me-now", "replace_with_new",
        "<api-key>", "[api-key]",
    ])
    def test_substring_placeholder_values(self, value):
        assert is_placeholder_api_key(value) is True

    def test_empty_string(self):
        assert is_placeholder_api_key("") is False

    def test_none(self):
        assert is_placeholder_api_key(None) is False

    def test_real_key_not_placeholder(self):
        assert is_placeholder_api_key("sk-abc123def456ghi789") is False

    def test_whitespace_only_not_placeholder(self):
        assert is_placeholder_api_key("   ") is False

    def test_case_insensitive(self):
        assert is_placeholder_api_key("NULL") is True
        assert is_placeholder_api_key("None") is True
        assert is_placeholder_api_key("TEST") is True


class TestIsValidApiKey:
    def test_rejects_none(self):
        assert is_valid_api_key(None) is False

    def test_rejects_empty(self):
        assert is_valid_api_key("") is False

    def test_rejects_placeholder(self):
        assert is_valid_api_key("your-api-key") is False

    def test_accepts_real_key(self):
        assert is_valid_api_key("sk-abc123def456ghi789") is True

    def test_accepts_simple_key(self):
        assert is_valid_api_key("my-api-key-12345") is True

    def test_rejects_whitespace_only(self):
        assert is_valid_api_key("   ") is False


class TestTruncateApiKey:
    def test_short_key_unchanged(self):
        assert truncate_api_key("short-key") == "short-key"

    def test_none_returns_none(self):
        assert truncate_api_key(None) is None

    def test_empty_returns_empty(self):
        assert truncate_api_key("") == ""

    def test_long_key_truncated(self):
        key = "d1el869r01qghj41hahgd1el869r01qghj41hai0"
        result = truncate_api_key(key)
        assert result.startswith("d1el86...")
        assert result.endswith("41hai0")

    def test_exactly_12_chars_unchanged(self):
        key = "123456789012"
        assert truncate_api_key(key) == key

    def test_13_chars_truncated(self):
        key = "1234567890123"
        result = truncate_api_key(key)
        assert "..." in result


class TestShouldSkipApiKeyUpdate:
    def test_none_skips(self):
        assert should_skip_api_key_update(None) is True

    def test_empty_string_does_not_skip(self):
        assert should_skip_api_key_update("") is False

    def test_placeholder_skips(self):
        assert should_skip_api_key_update("your-api-key") is True

    def test_real_key_does_not_skip(self):
        assert should_skip_api_key_update("sk-real-key-123456") is False

    def test_truncated_value_skips(self):
        assert should_skip_api_key_update("sk-abc...xyz789") is True
