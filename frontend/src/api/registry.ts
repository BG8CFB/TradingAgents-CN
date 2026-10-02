import { request, type ApiResponse } from './request'

/**
 * 智能体身份注册表（后端 AgentRegistry 单一权威来源）。
 * 键集合 = slug / 内部键 / 报告键（含历史别名）/ event_key，值为 YAML 配置中文名。
 * 前端不得本地构建别名表或写死智能体名称。
 */
export type DisplayNameMap = Record<string, string>

const BASE = '/api/registry'

export const registryApi = {
  getDisplayNames(): Promise<ApiResponse<DisplayNameMap>> {
    return request.get(`${BASE}/display-names`)
  },
}
