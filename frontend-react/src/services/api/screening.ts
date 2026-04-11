import { apiClient } from '../http/client'
import type { ApiResponse } from '@/types/common.types'
import type {
  ScreeningFieldConfig,
  ScreeningRequest,
  ScreeningResponse,
  EnhancedScreeningRequest,
  EnhancedScreeningResponse,
  IndustryItem,
} from '@/types/screening.types'

/** 获取筛选字段配置 */
export function getScreeningFields(): Promise<ApiResponse<ScreeningFieldConfig>> {
  return apiClient.get<ScreeningFieldConfig>('/api/screening/fields')
}

/** 获取指定字段信息 */
export function getScreeningFieldInfo(fieldName: string): Promise<ApiResponse<Record<string, unknown>>> {
  return apiClient.get<Record<string, unknown>>(`/api/screening/fields/${encodeURIComponent(fieldName)}`)
}

/** 运行传统筛选 */
export function runScreening(data: ScreeningRequest): Promise<ApiResponse<ScreeningResponse>> {
  return apiClient.post<ScreeningResponse>('/api/screening/run', data)
}

/** 运行增强筛选 */
export function runEnhancedScreening(data: EnhancedScreeningRequest): Promise<ApiResponse<EnhancedScreeningResponse>> {
  return apiClient.post<EnhancedScreeningResponse>('/api/screening/enhanced', data)
}

/** 验证筛选条件 */
export function validateScreeningConditions(conditions: EnhancedScreeningRequest['conditions']): Promise<ApiResponse<Record<string, unknown>>> {
  return apiClient.post<Record<string, unknown>>('/api/screening/validate', conditions)
}

/** 获取行业列表 */
export function getIndustries(): Promise<ApiResponse<{ industries: IndustryItem[]; total: number; source: string }>> {
  return apiClient.get<{ industries: IndustryItem[]; total: number; source: string }>('/api/screening/industries')
}
