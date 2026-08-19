"""LLM 默认配置常量 — 后端所有默认值的单一源头。

语义约定（勿混淆）：
- max_tokens     单次请求输出上限（发给 API 的值）
- context_window 模型上下文窗口（输入能力，仅供压缩层计算，绝不发给 max_tokens 参数）
"""

DEFAULT_MAX_TOKENS: int = 128_000
DEFAULT_TEMPERATURE: float = 0.7
DEFAULT_TIMEOUT: int = 180
DEFAULT_RETRY_TIMES: int = 3
DEFAULT_CONTEXT_WINDOW: int = 128_000

MAX_TOKENS_MIN: int = 1
MAX_TOKENS_MAX: int = 128_000

# 截断恢复：stop_reason=max_tokens 时升级到的输出上限（对齐 claude-code
# context.ts ESCALATED_MAX_TOKENS；仅作升级目标与 upper_limit 下限，不是默认值）
ESCALATED_MAX_TOKENS: int = 64_000

DEFAULT_LLM_FIELD_FALLBACKS: dict[str, int | float] = {
    "max_tokens": DEFAULT_MAX_TOKENS,
    "temperature": DEFAULT_TEMPERATURE,
    "timeout": DEFAULT_TIMEOUT,
    "retry_times": DEFAULT_RETRY_TIMES,
    "context_window": DEFAULT_CONTEXT_WINDOW,
}
