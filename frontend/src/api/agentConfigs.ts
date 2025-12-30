import { request, type ApiResponse } from './request'

export interface PhaseAgentMode {
  slug: string
  name: string
  roleDefinition: string
  description?: string
  whenToUse?: string
  groups?: string[]
  source?: string
  tools?: string[]
  initial_task?: string  // 初始任务描述（1阶段专用，系统会自动拼接股票信息）
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
