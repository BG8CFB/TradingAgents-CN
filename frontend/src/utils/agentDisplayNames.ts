import { registryApi } from '@/api/registry'

/**
 * 智能体中文显示名统一入口：后端 AgentRegistry 单一权威来源。
 * key（slug / 内部键 / 报告键含历史别名 / event_key）→ 显示名 的映射由
 * /api/registry/display-names 一次性下发，前端不再本地构建别名表。
 * 前端任何页面不得写死智能体中文显示名，一律消费本模块。
 */
let cache: Promise<Record<string, string>> | null = null

/** 加载显示名映射（模块级缓存，页面共享；失败降级为空映射，由调用方按 key 兜底） */
export function loadAgentDisplayNames(force = false): Promise<Record<string, string>> {
  if (!force && cache) return cache
  cache = registryApi
    .getDisplayNames()
    .then(res => res?.data ?? {})
    .catch(() => ({}))
  return cache
}
