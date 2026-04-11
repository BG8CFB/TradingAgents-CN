/**
 * 智能体管理 API
 * 对应后端 app/routers/agents.py（前缀 /api/agents）
 */

import apiClient from '../http/client'
import type { ApiResponse } from '@/types/common.types'

export interface AgentItem {
  id: string
  name: string
  stage: string
  type: string
  description?: string
  prompt?: string
  enabled: boolean
  is_system: boolean
}

/** 获取所有智能体（系统 + 自定义合并列表） */
export async function listAgents(): Promise<ApiResponse<AgentItem[]>> {
  return apiClient.get<AgentItem[]>('/api/agents')
}

/** 保存/更新智能体配置 */
export async function saveAgent(agent: Omit<AgentItem, 'is_system'>): Promise<ApiResponse<AgentItem>> {
  return apiClient.post<AgentItem>('/api/agents', agent)
}

/** 删除智能体（系统智能体重置为默认，自定义智能体真正删除） */
export async function deleteAgent(agentId: string): Promise<ApiResponse<{ success: boolean; message: string }>> {
  return apiClient.delete<{ success: boolean; message: string }>(`/api/agents/${agentId}`)
}
