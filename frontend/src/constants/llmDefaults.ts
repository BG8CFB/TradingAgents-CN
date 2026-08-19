/**
 * LLM 默认配置常量
 * 与后端 app/constants/llm_defaults.py 保持同步
 */
export const DEFAULT_MAX_TOKENS = 128000
export const DEFAULT_TEMPERATURE = 0.7
export const DEFAULT_TIMEOUT = 180
export const DEFAULT_RETRY_TIMES = 3

// 与后端 llm_defaults.py 同步：max_tokens（单次输出上限）封顶 / 截断升级封顶 / 上下文窗口兜底
export const MAX_TOKENS_MAX = 128000
export const ESCALATED_MAX_TOKENS = 64000
export const DEFAULT_CONTEXT_WINDOW = 128000

export const DEFAULT_LLM_CONFIG = {
  max_tokens: DEFAULT_MAX_TOKENS,
  temperature: DEFAULT_TEMPERATURE,
  timeout: DEFAULT_TIMEOUT,
  retry_times: DEFAULT_RETRY_TIMES,
  enabled: true,
} as const
