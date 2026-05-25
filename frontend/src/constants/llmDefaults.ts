/**
 * LLM 默认配置常量
 * 与后端 app/constants/llm_defaults.py 保持同步
 */
export const DEFAULT_MAX_TOKENS = 128000
export const DEFAULT_TEMPERATURE = 0.7
export const DEFAULT_TIMEOUT = 180
export const DEFAULT_RETRY_TIMES = 3

export const DEFAULT_LLM_CONFIG = {
  max_tokens: DEFAULT_MAX_TOKENS,
  temperature: DEFAULT_TEMPERATURE,
  timeout: DEFAULT_TIMEOUT,
  retry_times: DEFAULT_RETRY_TIMES,
  enabled: true,
} as const
