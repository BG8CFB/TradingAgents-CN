import type { ApiResponse } from '@/types/common.types'
import apiClient from '../http/client'

export interface AgentMode {
  slug: string
  name: string
  roleDefinition: string
  description?: string
  whenToUse?: string
  groups?: string[]
  source?: string
  tools?: string[]
  initial_task?: string
}

export interface AgentConfig {
  phase: number
  exists: boolean
  customModes: AgentMode[]
  path?: string
}

export function getAgentConfig(phase: number): Promise<ApiResponse<AgentConfig>> {
  return apiClient.get(`/api/agent-configs/${phase}`)
}
