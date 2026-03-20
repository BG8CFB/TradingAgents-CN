/**
 * MCP 工具类型定义
 */

export interface MCPTool {
  name: string
  description: string
  source: 'local-mcp'
  category: string
  available: boolean
  tushare_only: boolean
  enabled: boolean
}

export interface ToolCategorySummary {
  total: number
  available: number
  enabled: number
}

export interface MCPToolsSummary {
  total: number
  available: number
  unavailable: number
  enabled: number
  disabled: number
  tushare_only: number
  tushare_available: boolean
}

export interface MCPToolsResponse {
  success: boolean
  data: MCPTool[]
  count: number
  summary: MCPToolsSummary
}

export interface ToolToggleResponse {
  success: boolean
  data: {
    name: string
    enabled: boolean
    message: string
  }
}

export interface ToolAvailabilitySummary {
  success: boolean
  data: {
    total: number
    available: number
    unavailable: number
    enabled: number
    disabled: number
    tushare_available: boolean
    by_category: Record<string, ToolCategorySummary>
    disabled_tools: string[]
  }
}
