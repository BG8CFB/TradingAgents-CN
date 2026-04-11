/**
 * 工具管理 API
 * 对应后端 app/routers/tools.py（前缀 /api/tools）
 */

import apiClient from '../http/client'
import type { ApiResponse } from '@/types/common.types'

export interface ToolInfo {
  name: string
  description: string
  source: string
}

export interface MCPToolInfo extends ToolInfo {
  category: string
  available: boolean
  tushare_only: boolean
  enabled: boolean
}

/** 获取可用工具列表 */
export async function listAvailableTools(includeMcp = true): Promise<ApiResponse<{ data: ToolInfo[]; count: number }>> {
  return apiClient.get<{ data: ToolInfo[]; count: number }>('/api/tools/available', { include_mcp: String(includeMcp) })
}

/** 列出本地 MCP 工具 */
export async function listMCPTools(): Promise<ApiResponse<{
  data: MCPToolInfo[]
  count: number
  summary: {
    total: number; available: number; unavailable: number
    enabled: number; disabled: number
    tushare_only: number; tushare_available: boolean
  }
}>> {
  return apiClient.get<{
    data: MCPToolInfo[]
    count: number
    summary: {
      total: number; available: number; unavailable: number
      enabled: number; disabled: number
      tushare_only: number; tushare_available: boolean
    }
  }>('/api/tools/mcp')
}

/** 启用/禁用 MCP 工具 */
export async function toggleMCPTool(name: string, enabled: boolean): Promise<ApiResponse<{ data: { name: string; enabled: boolean; message: string } }>> {
  return apiClient.patch<{ data: { name: string; enabled: boolean; message: string } }>(`/api/tools/mcp/${name}/toggle`, { enabled })
}

/** 获取 MCP 工具可用性摘要 */
export async function getMCPAvailabilitySummary(): Promise<ApiResponse<{
  data: {
    total: number; available: number; unavailable: number
    enabled: number; disabled: number
    tushare_available: boolean
    by_category: Record<string, { total: number; available: number; enabled: number }>
    disabled_tools: string[]
  }
}>> {
  return apiClient.get<{
    data: {
      total: number; available: number; unavailable: number
      enabled: number; disabled: number
      tushare_available: boolean
      by_category: Record<string, { total: number; available: number; enabled: number }>
      disabled_tools: string[]
    }
  }>('/api/tools/mcp/availability-summary')
}
