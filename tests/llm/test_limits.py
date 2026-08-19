"""输出上限 / 上下文窗口解析测试（真实代码路径，无 mock）

覆盖 app/llm/limits.py 单一解析器 + providers bundle 集成：
- 解析优先级：llm_configs 显式值 > model_catalog > 环境变量 > 常量兜底
- upper_limit 截断升级封顶语义
- context_window 断链修复（catalog context_length 真正被消费）
- 2026-08-19 事故回归：任何路径不再回落 4096 小默认
"""

import pytest

from app.constants.llm_defaults import (
    DEFAULT_CONTEXT_WINDOW,
    DEFAULT_MAX_TOKENS,
    ESCALATED_MAX_TOKENS,
    MAX_TOKENS_MAX,
)
from app.llm.limits import (
    fallback_context_window,
    resolve_output_limits,
    set_catalog_index,
)


@pytest.fixture(autouse=True)
def _clean_catalog():
    """每个用例后清空注入的 catalog 索引，避免用例间泄漏"""
    yield
    set_catalog_index({})


def _inject_catalog(provider: str, model: str, *, context_length=None, max_tokens=None):
    set_catalog_index(
        {
            f"{provider}|{model}": {
                "context_length": context_length,
                "max_tokens": max_tokens,
            }
        }
    )


class TestMaxTokensPriority:
    def test_explicit_db_value_beats_catalog(self):
        _inject_catalog("ark", "m1", context_length=200_000, max_tokens=64_000)
        limits = resolve_output_limits("m1", "ark", db_max_tokens=32_000)
        assert limits.max_tokens == 32_000  # 用户显式配置压过目录默认

    def test_catalog_beats_env_and_constant(self, monkeypatch):
        monkeypatch.setenv("LLM_DEFAULT_MAX_TOKENS", "16000")
        _inject_catalog("ark", "m1", max_tokens=64_000)
        limits = resolve_output_limits("m1", "ark")
        assert limits.max_tokens == 64_000

    def test_env_beats_constant_default(self, monkeypatch):
        monkeypatch.setenv("LLM_DEFAULT_MAX_TOKENS", "16000")
        limits = resolve_output_limits("unknown-model")
        assert limits.max_tokens == 16_000

    def test_constant_fallback_never_small(self):
        """事故回归：无任何配置时兜底 128000，绝不是旧 4096"""
        limits = resolve_output_limits("totally-unknown")
        assert limits.max_tokens == DEFAULT_MAX_TOKENS == 128_000

    def test_invalid_env_ignored(self, monkeypatch):
        monkeypatch.setenv("LLM_DEFAULT_MAX_TOKENS", "not-a-number")
        assert resolve_output_limits("x").max_tokens == DEFAULT_MAX_TOKENS

    def test_env_capped_at_max(self, monkeypatch):
        monkeypatch.setenv("LLM_DEFAULT_MAX_TOKENS", "999999999")
        assert resolve_output_limits("x").max_tokens == MAX_TOKENS_MAX


class TestUpperLimit:
    def test_upper_at_least_escalated_without_catalog(self):
        # 无 catalog 时 upper 基线为 ESCALATED；默认 max_tokens 128000 更大 → 跟随并封顶
        limits = resolve_output_limits("x")
        assert limits.upper_limit == MAX_TOKENS_MAX
        small = resolve_output_limits("x", db_max_tokens=8_192)
        assert small.upper_limit == ESCALATED_MAX_TOKENS

    def test_upper_uses_catalog_max_when_larger(self):
        _inject_catalog("ark", "m1", max_tokens=100_000)
        limits = resolve_output_limits("m1", "ark")
        assert limits.upper_limit == 100_000

    def test_upper_raised_to_explicit_max_tokens(self):
        # 显式配置 128000 > 目录 64000 → upper 跟随用户配置（封顶 MAX_TOKENS_MAX）
        _inject_catalog("ark", "m1", max_tokens=64_000)
        limits = resolve_output_limits("m1", "ark", db_max_tokens=MAX_TOKENS_MAX)
        assert limits.upper_limit == MAX_TOKENS_MAX
        assert limits.max_tokens == MAX_TOKENS_MAX

    def test_upper_never_exceeds_global_max(self):
        _inject_catalog("ark", "m1", max_tokens=10_000_000)
        assert resolve_output_limits("m1", "ark").upper_limit == MAX_TOKENS_MAX


class TestContextWindow:
    def test_db_value_beats_catalog(self):
        _inject_catalog("ark", "m1", context_length=200_000)
        limits = resolve_output_limits("m1", "ark", db_context_window=500_000)
        assert limits.context_window == 500_000

    def test_catalog_context_length_consumed(self):
        """断链修复回归：catalog context_length 真正进入解析结果"""
        _inject_catalog("ark", "m1", context_length=1_000_000)
        limits = resolve_output_limits("m1", "ark")
        assert limits.context_window == 1_000_000

    def test_unknown_window_is_none_with_fallback(self):
        limits = resolve_output_limits("unknown-model")
        assert limits.context_window is None
        assert fallback_context_window(limits) == DEFAULT_CONTEXT_WINDOW


class TestCatalogLookup:
    def test_model_name_fallback_without_provider(self):
        _inject_catalog("SomeProvider", "m1", max_tokens=64_000)
        limits = resolve_output_limits("m1")  # 不传 provider
        assert limits.max_tokens == 64_000


class TestBundleIntegration:
    """providers._resolve_role_bundle 真实路径（内存配置，不触网）"""

    @pytest.fixture(autouse=True)
    def _fix_ssl_env(self, monkeypatch):
        """宿主机 SSL_CERT_FILE 常指向不存在的 Miniconda 路径，客户端构造时会炸；
        指回 certifi 真实证书（环境修正，非 mock）"""
        import certifi

        monkeypatch.setenv("SSL_CERT_FILE", certifi.where())
        monkeypatch.setenv("REQUESTS_CA_BUNDLE", certifi.where())

    @pytest.mark.asyncio
    async def test_bundle_carries_resolved_limits(self):
        from app.llm.providers import _resolve_role_bundle

        configs = [
            {
                "provider": "ark",
                "model_name": "qwen-test",
                "api_key": "sk-test-only",
                "api_base": "https://example.invalid/v1",
                "enabled": True,
                "suitable_roles": ["both"],
                "priority": 1,
                "max_tokens": None,
                "temperature": None,
                "timeout": None,
                "retry_times": None,
                "context_window": None,
            }
        ]
        catalog = {
            "ark|qwen-test": {"context_length": 1_000_000, "max_tokens": 100_000}
        }
        bundle = await _resolve_role_bundle("analyst", configs, {}, catalog)
        # 事故回归：DB 未配 max_tokens 时走 catalog/常量兜底，绝不回落 4096
        assert bundle.max_tokens == 100_000
        assert bundle.context_window == 1_000_000
        assert bundle.upper_limit == 100_000

    @pytest.mark.asyncio
    async def test_bundle_explicit_fields_win(self):
        from app.llm.providers import _resolve_role_bundle

        configs = [
            {
                "provider": "ark",
                "model_name": "qwen-test",
                "api_key": "sk-test-only",
                "api_base": "https://example.invalid/v1",
                "enabled": True,
                "suitable_roles": ["both"],
                "priority": 1,
                "max_tokens": 32_000,
                "temperature": 0.3,
                "timeout": None,
                "retry_times": None,
                "context_window": 250_000,
            }
        ]
        bundle = await _resolve_role_bundle("analyst", configs, {}, {})
        assert bundle.max_tokens == 32_000
        assert bundle.context_window == 250_000
        assert bundle.temperature == 0.3


class TestCompactConfigFromLimits:
    def test_large_window_tiered_buffer(self):
        from app.llm.compact.auto_compactor import CompactConfig

        cfg = CompactConfig(context_window=1_000_000, max_output_tokens=128_000)
        assert cfg.effective_buffer == 50_000  # ≥800k 档复活（此前拍死 128k）
        cfg400 = CompactConfig(context_window=400_000, max_output_tokens=128_000)
        assert cfg400.effective_buffer == 30_000
        cfg128 = CompactConfig(context_window=128_000, max_output_tokens=128_000)
        assert cfg128.effective_buffer == 13_000

    def test_effective_window_capped_output(self):
        from app.llm.compact.auto_compactor import CompactConfig

        cfg = CompactConfig(context_window=200_000, max_output_tokens=128_000)
        # 输出扣减封顶 20000（MAX_OUTPUT_TOKENS_FOR_SUMMARY）
        assert cfg.effective_window == 200_000 - 20_000


class TestIncidentRegression:
    def test_no_small_default_anywhere(self):
        """所有解析路径的 max_tokens 都必须 ≥ ESCALATED_MAX_TOKENS 或等于用户显式值"""
        for kwargs in (
            {},
            {"db_max_tokens": None},
            {"provider": "ark"},
        ):
            limits = resolve_output_limits("any-model", **kwargs)
            assert limits.max_tokens >= ESCALATED_MAX_TOKENS

    def test_runner_default_config_not_small(self):
        from app.llm.config import load_config

        cfg = load_config()
        assert cfg.max_tokens == DEFAULT_MAX_TOKENS
