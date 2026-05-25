/**
 * 工具类型定义（统一版）
 */

// ── 工具类型枚举（三类） ──
export type ToolType = 'builtin' | 'mcp' | 'skill'

// ── 可用性状态枚举 ──
export type AvailabilityStatus = 'available' | 'no_data' | 'unavailable' | 'unknown'

// ── 统一工具接口 ──
export interface UnifiedTool {
  name: string
  description: string
  tool_type: ToolType
  display_name: string
  source: string
  availability: {
    status: AvailabilityStatus
    detail: string
  }
}

// ── 统一工具列表响应 ──
export interface UnifiedToolsResponse {
  success: boolean
  data: UnifiedTool[]
  count: number
}

// ── 工具类型中文映射 ──
export const TOOL_TYPE_LABELS: Record<ToolType, string> = {
  builtin: '内置',
  mcp: 'MCP',
  skill: '技能',
}

// ── 工具类型颜色映射（Element Plus Tag type） ──
export const TOOL_TYPE_COLORS: Record<ToolType, string> = {
  builtin: 'primary',
  mcp: 'warning',
  skill: 'danger',
}

// ── 可用性状态中文映射 ──
export const AVAILABILITY_LABELS: Record<AvailabilityStatus, string> = {
  available: '有数据',
  no_data: '暂无数据',
  unavailable: '不可用',
  unknown: '未知',
}

// ── 可用性状态颜色映射 ──
export const AVAILABILITY_COLORS: Record<AvailabilityStatus, string> = {
  available: 'success',
  no_data: 'warning',
  unavailable: 'danger',
  unknown: 'info',
}

// ══════════════════════════════════════════════════
// 旧版 MCP Provider 工具类型（已废弃，保留向后兼容）
// 新代码请使用 types/mcp.ts 中的 MCPTool 接口
// ══════════════════════════════════════════════════

/** @deprecated 请使用 types/mcp.ts 中的 MCPTool */
export interface LegacyMCPTool {
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
  data: LegacyMCPTool[]
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
