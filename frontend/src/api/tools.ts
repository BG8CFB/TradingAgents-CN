import { request } from './request'
import type { UnifiedToolsResponse } from '@/types/tools'

// ── 统一工具 API ──

export const toolsApi = {
  /**
   * 获取统一工具清单（含类型分类和可用性状态）
   */
  listUnified(includeMcp = true, withAvailability = true): Promise<UnifiedToolsResponse> {
    return request.get('/api/tools/available', {
      params: { include_mcp: includeMcp, with_availability: withAvailability }
    })
  }
}

export type { UnifiedTool, UnifiedToolsResponse } from '@/types/tools'
