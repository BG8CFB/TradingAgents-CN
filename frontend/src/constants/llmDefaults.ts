/**
 * LLM 默认配置常量
 * 与后端 app/constants/llm_defaults.py 保持同步
 */
export const DEFAULT_MAX_TOKENS = 128000
export const DEFAULT_TEMPERATURE = 0.7
export const DEFAULT_TIMEOUT = 180
export const DEFAULT_RETRY_TIMES = 3

// 与后端 llm_defaults.py 同步：max_tokens（单次输出上限）封顶 / 上下文窗口兜底
export const MAX_TOKENS_MAX = 128000
export const DEFAULT_CONTEXT_WINDOW = 128000

export const DEFAULT_LLM_CONFIG = {
  max_tokens: DEFAULT_MAX_TOKENS,
  temperature: DEFAULT_TEMPERATURE,
  timeout: DEFAULT_TIMEOUT,
  retry_times: DEFAULT_RETRY_TIMES,
  enabled: true,
} as const

// 思考强度档位（与后端 app/constants/llm_defaults.py THINKING_EFFORT_LEVELS 同步）。
// 语义：空=不干预（不注入任何思考参数，与历史行为一致）；off=显式关闭；
// minimal/low/medium/high/max=开启并设定强度。各厂家方言映射见后端
// app/llm/protocols/thinking.py（前端只存 canonical 档位，不感知方言）。
export interface ThinkingEffortOption {
  value: string
  label: string
}

export const THINKING_EFFORT_OPTIONS: ThinkingEffortOption[] = [
  { value: '', label: '默认（不干预）' },
  { value: 'off', label: '关闭思考' },
  { value: 'minimal', label: '极简' },
  { value: 'low', label: '低' },
  { value: 'medium', label: '中' },
  { value: 'high', label: '高' },
  { value: 'max', label: '极限' },
]

// 模型名 → 推荐档位（新增模型时智能预填；仅新增时生效，编辑不覆盖已有值）。
// 与后端 thinking.py 的方言能力门控同口径：非思考模型不预填。
const THINKING_MODEL_PATTERNS: { pattern: RegExp; effort: string }[] = [
  { pattern: /^(o1|o3|o4)(-mini|-preview)?$/i, effort: 'high' },
  { pattern: /^gpt-5/i, effort: 'medium' },
  { pattern: /deepseek-(v4|v3\.1[.\d]*|r1|reasoner)/i, effort: 'high' },
  { pattern: /kimi/i, effort: 'high' },
  { pattern: /^glm-(4\.[5-9]\d*|5)/i, effort: 'high' },
  { pattern: /^(qwen|qwq).*?(thinking|plus|max|turbo)/i, effort: 'medium' },
  { pattern: /^gemini-(2\.5|3)/i, effort: 'medium' },
  { pattern: /^(claude|anthropic)/i, effort: 'medium' },
]

/** 按模型名推荐思考档位；非思考模型返回 ''（不干预） */
export function suggestThinkingEffort(modelName: string): string {
  const name = (modelName || '').split('/').pop()?.trim() || ''
  if (!name) return ''
  for (const { pattern, effort } of THINKING_MODEL_PATTERNS) {
    if (pattern.test(name)) return effort
  }
  return ''
}
