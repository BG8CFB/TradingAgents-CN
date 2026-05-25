"""LLM 默认配置常量 — 后端所有默认值的单一源头。"""

DEFAULT_MAX_TOKENS: int = 128_000
DEFAULT_TEMPERATURE: float = 0.7
DEFAULT_TIMEOUT: int = 180
DEFAULT_RETRY_TIMES: int = 3

MAX_TOKENS_MIN: int = 1
MAX_TOKENS_MAX: int = 128_000

DEFAULT_LLM_FIELD_FALLBACKS: dict[str, int | float] = {
    "max_tokens": DEFAULT_MAX_TOKENS,
    "temperature": DEFAULT_TEMPERATURE,
    "timeout": DEFAULT_TIMEOUT,
    "retry_times": DEFAULT_RETRY_TIMES,
}
