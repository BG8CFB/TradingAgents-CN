import { agentConfigApi } from '@/api/agentConfigs'

/**
 * 智能体中文显示名统一入口：从后端 agent 配置（阶段 1-3）构建
 * key（slug / 内部键 / 报告键）→ 显示名 的映射。
 * 前端任何页面不得写死智能体中文显示名，一律消费本模块。
 */

/** 报告/内部 key → agent slug 别名（纯键名对应；中文名一律来自后端配置） */
const REPORT_KEY_SLUG_ALIAS: Record<string, string> = {
  trader_investment_plan: 'trader',
  investment_plan: 'trader',
  final_trade_decision: 'trader',
  research_team_decision: 'research-manager',
  risk_management_decision: 'risk-manager',
  risk_manager_decision: 'risk-manager',
}

/** slug → 报告/状态键前缀（与后端 build_analyst_specs 一致） */
function baseKey(slug: string): string {
  return slug.replace(/-analyst$/, '').replace(/-/g, '_')
}

let cache: Promise<Record<string, string>> | null = null

/** 加载全部阶段配置并构建 key→显示名映射（模块级缓存，页面共享） */
export function loadAgentDisplayNames(force = false): Promise<Record<string, string>> {
  if (!force && cache) return cache
  cache = Promise.all([1, 2, 3].map(p => agentConfigApi.getPhase(p).catch(() => null)))
    .then(results => {
      const slugNames: Record<string, string> = {}
      const names: Record<string, string> = {}
      for (const res of results) {
        for (const mode of res?.data?.customModes ?? []) {
          if (!mode.slug) continue
          const name = mode.name || mode.slug
          slugNames[mode.slug] = name
          const base = baseKey(mode.slug)
          names[mode.slug] = name
          names[base] = name
          names[`${base}_report`] = name
          names[`${base}_analyst`] = name
        }
      }
      for (const [key, slug] of Object.entries(REPORT_KEY_SLUG_ALIAS)) {
        if (slugNames[slug]) names[key] = slugNames[slug]
      }
      return names
    })
  return cache
}
