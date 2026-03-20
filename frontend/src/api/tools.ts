import { request, type ApiResponse } from './request'
import type {
  MCPTool,
  MCPToolsResponse,
  ToolAvailabilitySummary,
  ToolToggleResponse
} from '@/types/tools'

export interface AvailableTool {
  name: string
  description?: string
  source?: string
}

export const toolsApi = {
  list(includeMcp = true): Promise<ApiResponse<AvailableTool[]>> {
    return request.get('/api/tools/available', { params: { include_mcp: includeMcp } })
  },

  /**
   * 列出所有 MCP 工具
   */
  listMCP(): Promise<ApiResponse<MCPToolsResponse>> {
    return request.get('/api/tools/mcp')
  },

  /**
   * 获取可用性摘要
   */
  getAvailabilitySummary(): Promise<ApiResponse<ToolAvailabilitySummary>> {
    return request.get('/api/tools/mcp/availability-summary')
  },

  /**
   * 切换工具启用状态
   */
  toggle(name: string, enabled: boolean): Promise<ApiResponse<ToolToggleResponse>> {
    return request.patch(`/api/tools/mcp/${name}/toggle`, { enabled })
  }
}

export type { MCPTool, MCPToolsResponse, ToolAvailabilitySummary, ToolToggleResponse }

