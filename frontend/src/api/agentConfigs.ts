import { request, type ApiResponse } from './request'

/**
 * 智能体配置模型（2026-08 工具体系四路拆分后）：
 * - data_tools: 预注入数据源 id（代码控制，分析师启动时预取注入上下文）
 * - mcp_tools / skills: 可调用工具限制集合；缺省/空 = 默认全部可用
 * - 内置工具（calc）全员默认，不经配置
 */
export interface PhaseAgentMode {
  slug: string
  name: string
  roleDefinition: string
  description?: string
  data_tools?: string[]
  mcp_tools?: string[]
  skills?: string[]
}

export interface PhaseAgentConfig {
  phase: number
  exists: boolean
  customModes: PhaseAgentMode[]
  path?: string
}

export interface PhaseAgentPayload {
  customModes: PhaseAgentMode[]
}

const BASE = '/api/agent-configs'

export const agentConfigApi = {
  getPhase(phase: number): Promise<ApiResponse<PhaseAgentConfig>> {
    return request.get(`${BASE}/${phase}`)
  },
  savePhase(phase: number, payload: PhaseAgentPayload): Promise<ApiResponse<PhaseAgentConfig>> {
    return request.put(`${BASE}/${phase}`, payload)
  }
}
