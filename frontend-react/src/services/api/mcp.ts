/**
 * MCP 服务管理 API
 * 对应后端 app/routers/mcp.py（前缀 /api/mcp）
 */

import apiClient from '../http/client'
import type { ApiResponse } from '@/types/common.types'

export interface MCPConnector {
  id: string
  name: string
  type: 'stdio' | 'http'
  config: Record<string, unknown>
  enabled: boolean
  status: 'connected' | 'disconnected' | 'error' | 'stopped' | 'unavailable' | 'unknown'
  healthInfo?: Record<string, unknown>
}

export interface MCPTool {
  name: string
  description: string
  serverName: string
  available: boolean
  status?: string
}

/** 列出所有 MCP 连接器 */
export async function listMCPConnectors(): Promise<ApiResponse<MCPConnector[]>> {
  return apiClient.get<MCPConnector[]>('/api/mcp/connectors')
}

/** 更新 MCP 连接器配置 */
export async function updateMCPConnectors(mcpServers: Record<string, unknown>): Promise<ApiResponse<Record<string, never>>> {
  return apiClient.post<Record<string, never>>('/api/mcp/connectors/update', { mcpServers })
}

/** 切换 MCP 连接器启用状态 */
export async function toggleMCPConnector(name: string, enabled: boolean): Promise<ApiResponse<{ enabled: boolean; status: string; message: string }>> {
  return apiClient.patch<{ enabled: boolean; status: string; message: string }>(`/api/mcp/connectors/${name}/toggle`, { enabled })
}

/** 删除 MCP 连接器 */
export async function deleteMCPConnector(name: string): Promise<ApiResponse<Record<string, never>>> {
  return apiClient.delete<Record<string, never>>(`/api/mcp/connectors/${name}`)
}

/** 列出所有 MCP 工具 */
export async function listAllMCPTools(): Promise<ApiResponse<{ data: MCPTool[]; serverStats: Record<string, { total: number; available: number; status: string }> }>> {
  return apiClient.get<{ data: MCPTool[]; serverStats: Record<string, { total: number; available: number; status: string }> }>('/api/mcp/tools')
}

/** 获取 MCP 健康状态 */
export async function getMCPHealth(): Promise<ApiResponse<Record<string, unknown>>> {
  return apiClient.get<Record<string, unknown>>('/api/mcp/health')
}

/** 重载 MCP 配置 */
export async function reloadMCPConfig(): Promise<ApiResponse<{ success: boolean; message: string }>> {
  return apiClient.post<{ success: boolean; message: string }>('/api/mcp/reload')
}

/** 重启指定 MCP 服务器 */
export async function restartMCPServer(name: string): Promise<ApiResponse<{ success: boolean; message: string }>> {
  return apiClient.post<{ success: boolean; message: string }>(`/api/mcp/servers/${name}/restart`)
}

/** 获取指定 MCP 服务器状态 */
export async function getMCPServerStatus(name: string): Promise<ApiResponse<{ data: { name: string; status: string; healthInfo?: Record<string, unknown> } }>> {
  return apiClient.get<{ data: { name: string; status: string; healthInfo?: Record<string, unknown> } }>(`/api/mcp/servers/${name}/status`)
}

/** 触发健康检查 */
export async function triggerMCPHealthCheck(): Promise<ApiResponse<{ success: boolean; message: string; data: Record<string, unknown> }>> {
  return apiClient.post<{ success: boolean; message: string; data: Record<string, unknown> }>('/api/mcp/health-check')
}
