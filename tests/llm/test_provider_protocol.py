"""厂家级请求协议解析测试（纯函数，真实代码路径，无 mock）

协议已上移到厂家配置（llm_providers.protocol）：
- 厂家显式 protocol 优先
- 厂家未填时按厂家名推断（anthropic/claude/ark/volcengine→anthropic，其余→openai）
- 模型配置不再携带 protocol（白名单已移除，残留字段被忽略）
"""

from app.llm.providers import (
    _CONFIG_FIELDS,
    _normalize_llm_configs,
    _normalize_provider_defaults,
    infer_protocol,
    resolve_provider,
)


def _cfg(provider: str, model: str = "test-model", **kw):
    return {
        "provider": provider,
        "model_name": model,
        "api_key": "sk-test",
        "api_base": "https://example.com/v1",
        "enabled": True,
        "suitable_roles": ["both"],
        "priority": 1,
        **kw,
    }


class TestInferProtocol:
    def test_explicit_provider_protocol_wins(self):
        assert infer_protocol("some_custom", "anthropic") == "anthropic"
        assert infer_protocol("anthropic", "openai") == "openai"

    def test_infer_by_provider_name(self):
        for name in ("anthropic", "Claude", "ark", "Volcengine"):
            assert infer_protocol(name) == "anthropic"
        for name in ("openai", "deepseek", "302ai", "custom_x", ""):
            assert infer_protocol(name) == "openai"

    def test_invalid_protocol_falls_back_to_infer(self):
        assert infer_protocol("openai", "grpc") == "openai"
        assert infer_protocol("anthropic", "grpc") == "anthropic"


class TestResolveProviderProtocol:
    def test_provider_level_protocol_used(self):
        resolved = resolve_provider(
            [_cfg("custom_x")],
            provider_defaults={"custom_x": {"api_key": "", "default_base_url": None, "protocol": "anthropic"}},
        )
        assert resolved is not None and resolved.protocol == "anthropic"

    def test_provider_without_protocol_inferred_by_name(self):
        resolved = resolve_provider(
            [_cfg("ark")],
            provider_defaults={"ark": {"api_key": "", "default_base_url": None, "protocol": None}},
        )
        assert resolved is not None and resolved.protocol == "anthropic"

    def test_legacy_model_level_protocol_ignored(self):
        # 存量 llm_configs 文档可能仍残留 protocol 字段：解析必须忽略它
        cfg = _cfg("openai", protocol="anthropic")
        resolved = resolve_provider([cfg], provider_defaults={})
        assert resolved is not None and resolved.protocol == "openai"

    def test_fallback_resolution_uses_provider_protocol(self):
        from app.llm.providers import _resolve_fallback

        configs = [
            _cfg("openai", "primary-model", priority=10),
            _cfg("custom_x", "fallback-model", priority=5),
        ]
        fallback = _resolve_fallback(
            configs, "both", "primary-model",
            provider_defaults={"custom_x": {"api_key": "sk-x", "default_base_url": None, "protocol": "anthropic"}},
        )
        assert fallback is not None and fallback.protocol == "anthropic"


class TestNormalize:
    def test_config_fields_excludes_protocol(self):
        assert "protocol" not in _CONFIG_FIELDS
        normalized = _normalize_llm_configs([_cfg("openai", protocol="anthropic")])
        assert len(normalized) == 1 and "protocol" not in normalized[0]

    def test_provider_defaults_include_protocol(self):
        defaults = _normalize_provider_defaults([
            {"name": "MyVendor", "api_key": "k", "default_base_url": "u", "protocol": "anthropic"},
            {"name": "other", "api_key": "k", "default_base_url": None},
        ])
        assert defaults["myvendor"]["protocol"] == "anthropic"
        assert defaults["other"]["protocol"] is None
