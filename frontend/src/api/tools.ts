import { request, type ApiResponse } from './request'
import type {
  UnifiedTool,
  UnifiedToolsResponse,
  MCPToolsResponse,
  ToolAvailabilitySummary,
  ToolToggleResponse
} from '@/types/tools'

// ── 统一工具 API（新版） ──

export const toolsApi = {
  /**
   * 获取统一工具清单（含类型分类和可用性状态）
   */
  listUnified(includeMcp = true, withAvailability = true): Promise<UnifiedToolsResponse> {
    return request.get('/api/tools/available', {
      params: { include_mcp: includeMcp, with_availability: withAvailability }
    })
  },

  // ── 向后兼容方法 ──

  /**
   * 获取工具列表（旧版，不含 tool_type）
   * @deprecated 使用 listUnified() 替代
   */
  list(includeMcp = true): Promise<ApiResponse<UnifiedTool[]>> {
    return request.get('/api/tools/available', {
      params: { include_mcp: includeMcp, with_availability: false }
    })
  },

  /**
   * 列出所有 MCP Provider 工具
   */
  listMCP(): Promise<MCPToolsResponse> {
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

export type { UnifiedTool, UnifiedToolsResponse } from '@/types/tools'
export type { MCPTool, MCPToolsResponse, ToolAvailabilitySummary, ToolToggleResponse } from '@/types/tools'
