"""思考强度方言映射测试（纯函数，真实代码路径，无 mock）

口径来源 docs/superpowers/specs/2026-08-30-thinking-effort-design.md
（2026-08-31 修订：方言收敛为 openai/deepseek/vllm/llamacpp/ollama 五类，
千问/智谱/Kimi/Gemini 移除；实测数据见 NAS 网关 vLLM 探针）：

- canonical 档位 off/minimal/low/medium/high/max，未设置=None 不注入
- OpenAI：reasoning_effort（max→xhigh）；gpt-5 系 off→none，o 系 off 不可关
- DeepSeek：三档（minimal→low、medium→high），off 不可关
- vLLM：chat_template_kwargs（off→enable_thinking=false；档位→reasoning_effort，
  Qwen3.8 模板限 low/medium/xhigh）+ 顶层 thinking_token_budget 硬预算
- llama.cpp：同 vLLM 的 ctk 形状；无请求级预算
- Ollama /v1：顶层 reasoning_effort 三档；无关闭、无预算
- Anthropic：档位 → budget_tokens 换算，显式预算优先
- 框架方言以 provider 名判定，不做模型门控、不参与模型名兜底
"""

import pytest

from app.constants.llm_defaults import THINKING_EFFORT_LEVELS
from app.llm.protocols.thinking import (
    _ANTHROPIC_BUDGET,
    _CTK_EFFORT,
    _CTK_EFFORT_QWEN38,
    _DIALECTS,
    _OPENAI_EFFORT,
    _OLLAMA_EFFORT,
    _TRINARY_EFFORT,
    build_openai_thinking_params,
    detect_dialect,
    merge_openai_thinking_params,
    resolve_anthropic_thinking_budget,
)


class TestDetectDialect:
    def test_provider_name_narrows_candidates(self):
        assert detect_dialect("deepseek", "deepseek-v4").name == "deepseek"
        assert detect_dialect("vllm", "Qwen3.8-27B").name == "vllm"
        assert detect_dialect("llama.cpp", "gpt-oss-120b").name == "llamacpp"

    def test_framework_dialect_no_model_gate(self):
        # 框架决定参数形状：任意模型名都接受（档位合法值由模型模板校验）
        assert detect_dialect("ollama", "whatever-model").name == "ollama"
        assert detect_dialect("vllm", "").name == "vllm"

    def test_provider_hit_beats_model_fallthrough(self):
        # provider 显式命中后不落模型名兜底：vllm 上的 o3 不走 OpenAI 方言
        assert detect_dialect("vllm", "openai/o3").name == "vllm"

    def test_provider_hit_but_model_not_thinking(self):
        # 云端方言 provider 命中但模型不匹配 → None（不注入）
        assert detect_dialect("openai", "gpt-4o") is None
        assert detect_dialect("deepseek", "deepseek-chat") is None

    def test_model_pattern_gates_injection(self):
        # 自定义厂家名（聚合网关）：provider 不命中，按模型名兜底识别
        assert detect_dialect("custom_gw", "gpt-5.1").name == "openai"
        assert detect_dialect("302ai", "openai/o3-mini").name == "openai"
        assert detect_dialect("openrouter", "deepseek/deepseek-v4").name == "deepseek"

    def test_framework_dialects_excluded_from_fallthrough(self):
        # match-all 的框架方言若参与兜底会吞掉一切未知模型
        assert detect_dialect(None, "llama-3-70b") is None
        assert detect_dialect(None, "") is None
        assert detect_dialect("custom", "Qwen3.8-27B") is None

    def test_unknown_returns_none(self):
        assert detect_dialect("zhipu", "glm-5.3") is None  # 方言已移除
        assert detect_dialect("moonshot", "kimi-k3") is None
        assert detect_dialect("gemini", "gemini-3-pro") is None

    def test_case_insensitive(self):
        assert detect_dialect("DeepSeek", "DeepSeek-V4").name == "deepseek"
        assert detect_dialect("vLLM", "Qwen3.8").name == "vllm"


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

    def test_budget_ignored(self):
        # OpenAI 官方无请求级预算参数，budget 不注入
        assert build_openai_thinking_params("openai", "o3", "high", budget=4096) == {
            "reasoning_effort": "high"
        }


class TestDeepSeekDialect:
    """DeepSeek：三档方言（官方兼容映射 minimal→low、medium→high）"""

    @pytest.mark.parametrize("model", ["deepseek-v4", "deepseek-v3.2", "deepseek-reasoner"])
    def test_level_mapping(self, model):
        assert build_openai_thinking_params("deepseek", model, "medium") == {"reasoning_effort": "high"}
        assert build_openai_thinking_params("deepseek", model, "minimal") == {"reasoning_effort": "low"}
        assert build_openai_thinking_params("deepseek", model, "max") == {"reasoning_effort": "max"}

    def test_off_not_supported(self):
        # 仅思考模型无法关闭 → 不注入（保守策略）
        assert build_openai_thinking_params("deepseek", "deepseek-v4", "off") == {}

    def test_legacy_v3_not_gated(self):
        # deepseek-chat（V3，无思考）不注入
        assert build_openai_thinking_params("deepseek", "deepseek-chat", "high") == {}


class TestVllmDialect:
    """vLLM：ctk 档位/开关 + 顶层 thinking_token_budget（2026-08-31 实测形状）"""

    def test_off_hard_switch(self):
        assert build_openai_thinking_params("vllm", "Qwen3.8-27B", "off") == {
            "extra_body": {"chat_template_kwargs": {"enable_thinking": False}}
        }

    def test_generic_model_effort(self):
        # 非 Qwen3.8 模型走通用模板口径（low/medium/high）
        assert build_openai_thinking_params("vllm", "gpt-oss-120b", "high") == {
            "extra_body": {"chat_template_kwargs": {"reasoning_effort": "high"}}
        }
        assert build_openai_thinking_params("vllm", "gpt-oss-120b", "minimal") == {
            "extra_body": {"chat_template_kwargs": {"reasoning_effort": "low"}}
        }

    def test_qwen38_template_tiers(self):
        # Qwen3.8 模板只收 low/medium/xhigh：high→xhigh（发 high 必 400）
        assert build_openai_thinking_params("vllm", "Qwen3.8-27B", "high") == {
            "extra_body": {"chat_template_kwargs": {"reasoning_effort": "xhigh"}}
        }
        assert build_openai_thinking_params("vllm", "qwen3.8-8b", "max") == {
            "extra_body": {"chat_template_kwargs": {"reasoning_effort": "xhigh"}}
        }
        assert build_openai_thinking_params("vllm", "Qwen3.8-27B", "medium") == {
            "extra_body": {"chat_template_kwargs": {"reasoning_effort": "medium"}}
        }

    def test_budget_hard_cap(self):
        # 显式预算 → 顶层 thinking_token_budget（唯一确定性硬上限）
        assert build_openai_thinking_params("vllm", "Qwen3.8-27B", "low", budget=30) == {
            "extra_body": {
                "chat_template_kwargs": {"reasoning_effort": "low"},
                "thinking_token_budget": 30,
            }
        }
        # off + 预算：开关优先，预算仍带上（后端兼容）
        assert build_openai_thinking_params("vllm", "Qwen3.8-27B", "off", budget=10) == {
            "extra_body": {
                "chat_template_kwargs": {"enable_thinking": False},
                "thinking_token_budget": 10,
            }
        }

    def test_budget_only_without_effort(self):
        assert build_openai_thinking_params("vllm", "Qwen3.8-27B", None, budget=200) == {
            "extra_body": {"thinking_token_budget": 200}
        }


class TestLlamaCppDialect:
    def test_same_ctk_shape_as_vllm(self):
        assert build_openai_thinking_params("llamacpp", "Qwen3.8-27B", "high") == {
            "extra_body": {"chat_template_kwargs": {"reasoning_effort": "xhigh"}}
        }
        assert build_openai_thinking_params("llama-server", "gpt-oss-20b", "off") == {
            "extra_body": {"chat_template_kwargs": {"enable_thinking": False}}
        }

    def test_budget_not_request_level(self):
        # 预算须服务端 --reasoning-budget 配置，请求级不注入
        assert build_openai_thinking_params("llamacpp", "Qwen3.8-27B", "low", budget=30) == {
            "extra_body": {"chat_template_kwargs": {"reasoning_effort": "low"}}
        }
        assert build_openai_thinking_params("llamacpp", "Qwen3.8-27B", None, budget=30) == {}


class TestOllamaDialect:
    def test_three_tier_effort(self):
        assert build_openai_thinking_params("ollama", "qwen3:8b", "high") == {"reasoning_effort": "high"}
        assert build_openai_thinking_params("ollama", "qwen3:8b", "minimal") == {"reasoning_effort": "low"}
        assert build_openai_thinking_params("ollama", "qwen3:8b", "max") == {"reasoning_effort": "high"}

    def test_off_not_supported(self):
        # /v1 兼容层无关闭（原生 API think 字段才有）
        assert build_openai_thinking_params("ollama", "qwen3:8b", "off") == {}

    def test_budget_not_supported(self):
        assert build_openai_thinking_params("ollama", "qwen3:8b", None, budget=30) == {}
        assert build_openai_thinking_params("ollama", "qwen3:8b", "high", budget=30) == {
            "reasoning_effort": "high"
        }


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
            params, kwargs, provider="vllm", model="Qwen3.8-27B", effort="low", budget=30
        )
        assert kwargs["extra_body"] == {
            "custom_flag": 1,
            "chat_template_kwargs": {"reasoning_effort": "low"},
            "thinking_token_budget": 30,
        }
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
    """每个 canonical 档位在所有映射表/方言 builder 中必须有取值（防新增档位漏配）"""

    LEVELS = [lv for lv in THINKING_EFFORT_LEVELS if lv != "off"]

    def test_all_levels_covered_in_every_table(self):
        for effort in self.LEVELS:
            assert effort in _OPENAI_EFFORT, f"OpenAI 方言缺 {effort}"
            assert effort in _TRINARY_EFFORT, f"DeepSeek 方言缺 {effort}"
            assert effort in _CTK_EFFORT, f"ctk 通用口径缺 {effort}"
            assert effort in _CTK_EFFORT_QWEN38, f"Qwen3.8 口径缺 {effort}"
            assert effort in _OLLAMA_EFFORT, f"Ollama 方言缺 {effort}"
            assert effort in _ANTHROPIC_BUDGET, f"Anthropic 换算缺 {effort}"

    def test_every_dialect_builder_covers_all_levels(self):
        # 逐方言 × 逐档位跑真实 builder：off 特判之外任何档位不得 KeyError
        probe_models = {
            "openai": "o3",
            "deepseek": "deepseek-v4",
            "vllm": "Qwen3.8-27B",
            "llamacpp": "gpt-oss-120b",
            "ollama": "qwen3:8b",
        }
        for dialect in _DIALECTS:
            model = probe_models[dialect.name]
            for effort in self.LEVELS:
                result = build_openai_thinking_params(dialect.providers[0], model, effort)
                assert result != {}, f"{dialect.name} 方言 {effort} 档意外不注入"
            # off 也必须可调用（返回 {} 或关闭参数，不得异常）
            build_openai_thinking_params(dialect.providers[0], model, "off")

    def test_off_is_only_level_not_in_tables(self):
        # off 走各 builder 特判（能否关闭是模型能力，不是档位映射）
        assert "off" not in _OPENAI_EFFORT


class TestClientBurnIn:
    """客户端实例烙入链路：思考参数作为实例默认值随客户端构造烙入"""

    def test_factory_burns_thinking_params(self):
        from app.llm.core.factory import create_client

        client = create_client(
            "openai",
            model="Qwen3.8-27B",
            api_key="sk-test-not-called",
            base_url="https://example.com/v1",
            provider="vllm",
            thinking_effort="high",
            thinking_budget=30,
        )
        assert client.thinking_effort == "high"
        assert client.thinking_budget == 30
        assert client.provider == "vllm"

    def test_build_client_carries_provider_and_thinking(self):
        from app.llm.providers import ResolvedProvider, build_client

        resolved = ResolvedProvider(
            protocol="openai",
            model="Qwen3.8-27B",
            api_key="sk-test-not-called",
            base_url="https://example.com/v1",
            source="db",
            provider="vllm",
            thinking_effort="medium",
            thinking_budget=1024,
        )
        client = build_client(resolved)
        assert client.provider == "vllm"
        assert client.model == "Qwen3.8-27B"
        assert client.thinking_effort == "medium"
        assert client.thinking_budget == 1024

    def test_bundle_no_longer_carries_thinking_fields(self):
        # bundle 字段已删：调用方透传下线，实例默认接管（getattr 兜底会转发到
        # primary 的同名属性，故此处断言语义来自客户端而非 bundle 顶层字段）
        from app.llm.providers import EngineClientBundle, ResolvedProvider, build_client

        resolved = ResolvedProvider(
            protocol="openai",
            model="o3",
            api_key="sk-test-not-called",
            base_url="https://example.com/v1",
            source="db",
            provider="openai",
            thinking_effort="high",
        )
        bundle = EngineClientBundle(primary=build_client(resolved))
        assert not hasattr(EngineClientBundle, "thinking_budget")
        # __getattr__ 转发：读到的就是 primary 客户端烙入的实例默认
        assert bundle.thinking_effort == "high"

    def test_client_default_thinking_empty(self):
        from app.llm.providers import ResolvedProvider, build_client

        resolved = ResolvedProvider(
            protocol="openai",
            model="test-model",
            api_key="sk-test-not-called",
            base_url="https://example.com/v1",
            source="env",
        )
        client = build_client(resolved)
        assert client.provider == ""
        assert client.thinking_effort is None
        assert client.thinking_budget is None
