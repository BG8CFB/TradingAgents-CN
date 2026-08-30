"""思考强度方言映射测试（纯函数，真实代码路径，无 mock）

口径来源 docs/superpowers/specs/2026-08-30-thinking-effort-design.md：
- canonical 档位 off/minimal/low/medium/high/max，未设置=None 不注入
- OpenAI：reasoning_effort（max→xhigh）；gpt-5 系 off→none，o 系 off 不可关
- DeepSeek/Kimi：三档（minimal→low、medium→high），off 不可关
- GLM：4.5/4.6 仅开关；5.2+ 带 effort；5.3 不可关
- Qwen：extra_body enable_thinking + thinking_budget（上限 32768）
- Gemini：reasoning_effort，无 max 档回落 high
- Anthropic：档位 → budget_tokens 换算，显式预算优先
"""

import pytest

from app.constants.llm_defaults import THINKING_EFFORT_LEVELS
from app.llm.protocols.thinking import (
    _ANTHROPIC_BUDGET,
    _GEMINI_EFFORT,
    _OPENAI_EFFORT,
    _QWEN_BUDGET,
    _TRINARY_EFFORT,
    build_openai_thinking_params,
    detect_dialect,
    merge_openai_thinking_params,
    resolve_anthropic_thinking_budget,
)


class TestDetectDialect:
    def test_provider_name_narrows_candidates(self):
        assert detect_dialect("zhipu", "glm-5.3").name == "glm"
        assert detect_dialect("deepseek", "deepseek-v4").name == "deepseek"
        assert detect_dialect("moonshot", "kimi-k3").name == "kimi"

    def test_model_pattern_gates_injection(self):
        # 同厂家非思考模型：provider 命中但模型不匹配 → None（不注入）
        assert detect_dialect("openai", "gpt-4o") is None
        assert detect_dialect("zhipu", "glm-4-flash") is None
        # 自定义厂家名（聚合网关）：provider 不命中，按模型名兜底识别
        assert detect_dialect("custom_gw", "gpt-5.1").name == "openai"

    def test_aggregator_model_name_matches_suffix(self):
        # 聚合渠道模型名取 "/" 后段
        assert detect_dialect(None, "302ai/zhipu/glm-5.3").name == "glm"
        assert detect_dialect("302ai", "openai/o3-mini").name == "openai"
        assert detect_dialect("openrouter", "deepseek/deepseek-v4").name == "deepseek"

    def test_unknown_returns_none(self):
        assert detect_dialect("custom", "llama-3-70b") is None
        assert detect_dialect(None, "") is None

    def test_case_insensitive(self):
        assert detect_dialect("Zhipu", "GLM-5.2").name == "glm"
        assert detect_dialect("Qwen", "QWQ-32B").name == "qwen"


class TestOpenAIDialect:
    def test_effort_levels_map(self):
        assert build_openai_thinking_params("openai", "o3", "high") == {"reasoning_effort": "high"}
        assert build_openai_thinking_params("openai", "gpt-5.1", "max") == {"reasoning_effort": "xhigh"}
        assert build_openai_thinking_params("openai", "gpt-5.1", "minimal") == {"reasoning_effort": "minimal"}

    def test_off_gpt5_none_o_series_skipped(self):
        # gpt-5.1+ 支持 reasoning_effort=none；o1/o3/o4 无关闭档 → 不注入
        assert build_openai_thinking_params("openai", "gpt-5.1", "off") == {"reasoning_effort": "none"}
        assert build_openai_thinking_params("openai", "o3", "off") == {}
        assert build_openai_thinking_params("openai", "o4-mini", "off") == {}

    def test_unset_effort_injects_nothing(self):
        assert build_openai_thinking_params("openai", "o3", None) == {}
        assert build_openai_thinking_params("openai", "o3", "") == {}

    def test_non_thinking_model_no_injection(self):
        assert build_openai_thinking_params("openai", "gpt-4o", "high") == {}


class TestTrinaryDialect:
    """DeepSeek / Kimi：三档方言（官方兼容映射 minimal→low、medium→high）"""

    @pytest.mark.parametrize("model", ["deepseek-v4", "deepseek-v3.2", "deepseek-reasoner", "kimi-k3"])
    def test_level_mapping(self, model):
        provider = "deepseek" if model.startswith("deepseek") else "moonshot"
        assert build_openai_thinking_params(provider, model, "medium") == {"reasoning_effort": "high"}
        assert build_openai_thinking_params(provider, model, "minimal") == {"reasoning_effort": "low"}
        assert build_openai_thinking_params(provider, model, "max") == {"reasoning_effort": "max"}

    def test_off_not_supported(self):
        # 仅思考模型无法关闭 → 不注入（保守策略）
        assert build_openai_thinking_params("deepseek", "deepseek-v4", "off") == {}
        assert build_openai_thinking_params("moonshot", "kimi-k3", "off") == {}


class TestGLMDialect:
    def test_glm45_switch_only(self):
        # GLM-4.5/4.6 无档位，仅开/关
        assert build_openai_thinking_params("zhipu", "glm-4.6", "high") == {
            "extra_body": {"thinking": {"type": "enabled"}}
        }
        assert build_openai_thinking_params("zhipu", "glm-4.5", "off") == {
            "extra_body": {"thinking": {"type": "disabled"}}
        }

    def test_glm52_plus_has_effort(self):
        assert build_openai_thinking_params("zhipu", "glm-5.2", "max") == {
            "extra_body": {"thinking": {"type": "enabled", "effort": "max"}}
        }
        assert build_openai_thinking_params("zhipu", "glm-5.2", "off") == {
            "extra_body": {"thinking": {"type": "disabled"}}
        }

    def test_glm53_cannot_disable(self):
        assert build_openai_thinking_params("zhipu", "glm-5.3", "off") == {}
        assert build_openai_thinking_params("zhipu", "glm-5.3", "high") == {
            "extra_body": {"thinking": {"type": "enabled", "effort": "high"}}
        }


class TestQwenDialect:
    def test_enable_with_budget(self):
        assert build_openai_thinking_params("qwen", "qwen3-max", "high") == {
            "extra_body": {"enable_thinking": True, "thinking_budget": 32768}
        }
        # 百炼上限 32768：极限档与高档同值
        assert build_openai_thinking_params("qwen", "qwen3-max", "max") == {
            "extra_body": {"enable_thinking": True, "thinking_budget": 32768}
        }
        assert build_openai_thinking_params("qwen", "qwen-plus", "low") == {
            "extra_body": {"enable_thinking": True, "thinking_budget": 4096}
        }

    def test_off_respects_thinking_only_models(self):
        assert build_openai_thinking_params("qwen", "qwen3-max", "off") == {
            "extra_body": {"enable_thinking": False}
        }
        # 仅思考模式变体无法关闭 → 不注入
        assert build_openai_thinking_params("qwen", "qwen3-235b-thinking", "off") == {}


class TestGeminiDialect:
    def test_effort_with_max_fallback(self):
        # Gemini 无 max 档，极限档回落 high
        assert build_openai_thinking_params("gemini", "gemini-2.5-pro", "max") == {
            "reasoning_effort": "high"
        }
        assert build_openai_thinking_params("gemini", "gemini-3-pro", "low") == {
            "reasoning_effort": "low"
        }

    def test_off_not_supported_via_compat(self):
        assert build_openai_thinking_params("gemini", "gemini-2.5-pro", "off") == {}


class TestAnthropicBudget:
    def test_effort_conversion_table(self):
        assert resolve_anthropic_thinking_budget("minimal", None) == 1024
        assert resolve_anthropic_thinking_budget("low", None) == 4096
        assert resolve_anthropic_thinking_budget("medium", None) == 16384
        assert resolve_anthropic_thinking_budget("high", None) == 32768
        assert resolve_anthropic_thinking_budget("max", None) == 65536

    def test_explicit_budget_wins(self):
        assert resolve_anthropic_thinking_budget("high", 8192) == 8192
        assert resolve_anthropic_thinking_budget(None, 5000) == 5000

    def test_unset_returns_none(self):
        # Anthropic 思考是 opt-in：off 与未设置等价，均不开启
        assert resolve_anthropic_thinking_budget("off", None) is None
        assert resolve_anthropic_thinking_budget(None, None) is None
        assert resolve_anthropic_thinking_budget("", None) is None


class TestMergeBehavior:
    def test_extra_body_merged_not_overwritten(self):
        params: dict = {}
        kwargs = {"extra_body": {"custom_flag": 1}}
        merge_openai_thinking_params(
            params, kwargs, provider="qwen", model="qwen3-max", effort="low"
        )
        assert kwargs["extra_body"] == {"custom_flag": 1, "enable_thinking": True, "thinking_budget": 4096}
        assert "reasoning_effort" not in params

    def test_top_level_param_merges_into_params(self):
        params: dict = {}
        kwargs: dict = {}
        merge_openai_thinking_params(
            params, kwargs, provider="openai", model="o3", effort="high"
        )
        assert params == {"reasoning_effort": "high"}
        assert "extra_body" not in kwargs

    def test_no_injection_leaves_both_untouched(self):
        params = {"model": "gpt-4o"}
        kwargs = {"extra_body": {"x": 1}}
        merge_openai_thinking_params(
            params, kwargs, provider="openai", model="gpt-4o", effort="high"
        )
        assert params == {"model": "gpt-4o"}
        assert kwargs == {"extra_body": {"x": 1}}


class TestCanonicalCompleteness:
    """每个 canonical 档位在各方言映射表中必须有取值（防新增档位漏配 KeyError）"""

    LEVELS = [lv for lv in THINKING_EFFORT_LEVELS if lv != "off"]

    def test_all_levels_covered_in_every_dialect(self):
        for effort in self.LEVELS:
            assert effort in _OPENAI_EFFORT, f"OpenAI 方言缺 {effort}"
            assert effort in _TRINARY_EFFORT, f"三档方言缺 {effort}"
            assert effort in _GEMINI_EFFORT, f"Gemini 方言缺 {effort}"
            assert effort in _ANTHROPIC_BUDGET, f"Anthropic 换算缺 {effort}"
            assert effort in _QWEN_BUDGET, f"Qwen 预算缺 {effort}"

    def test_off_is_only_level_not_in_tables(self):
        # off 走各 builder 特判（能否关闭是模型能力，不是档位映射）
        assert "off" not in _OPENAI_EFFORT


class TestProviderBurnedIn:
    """工厂链路：provider 名烙入客户端实例（方言判定依赖）"""

    def test_build_client_carries_provider(self):
        from app.llm.providers import ResolvedProvider, build_client

        resolved = ResolvedProvider(
            protocol="openai",
            model="glm-5.3",
            api_key="sk-test-not-called",
            base_url="https://example.com/v1",
            source="db",
            provider="zhipu",
        )
        client = build_client(resolved)
        assert client.provider == "zhipu"
        assert client.model == "glm-5.3"

    def test_client_default_provider_empty(self):
        from app.llm.providers import ResolvedProvider, build_client

        resolved = ResolvedProvider(
            protocol="openai",
            model="test-model",
            api_key="sk-test-not-called",
            base_url="https://example.com/v1",
            source="env",
        )
        assert build_client(resolved).provider == ""
