import apiClient from '../http/client'
import type { ApiResponse } from '@/types/common.types'

export interface UsageRecord {
  id?: string
  timestamp: string
  provider: string
  model_name: string
  input_tokens: number
  output_tokens: number
  cost: number
  currency: string
  session_id: string
  analysis_type: string
  stock_code?: string
}

export interface UsageStatistics {
  total_requests: number
  total_input_tokens: number
  total_output_tokens: number
  total_cost: number
  cost_by_currency: Record<string, number>
  by_provider: Record<string, { requests: number; tokens: number; cost: number }>
  by_model: Record<string, { requests: number; tokens: number; cost: number }>
  by_date: Record<string, { requests: number; tokens: number; cost: number }>
}

/** 获取使用统计 */
export async function getUsageStatistics(days = 7): Promise<ApiResponse<UsageStatistics>> {
  return apiClient.get<UsageStatistics>('/api/usage/statistics', { days })
}

/** 获取按供应商统计的成本 */
export async function getCostByProvider(days = 7): Promise<ApiResponse<Record<string, { cost: number; count: number }>>> {
  return apiClient.get<Record<string, { cost: number; count: number }>>('/api/usage/cost/by-provider', { days })
}

/** 获取按模型统计的成本 */
export async function getCostByModel(days = 7): Promise<ApiResponse<Record<string, { cost: number; count: number }>>> {
  return apiClient.get<Record<string, { cost: number; count: number }>>('/api/usage/cost/by-model', { days })
}

/** 获取每日成本统计 */
export async function getDailyCost(days = 30): Promise<ApiResponse<Array<{ date: string; cost: number; tokens: number }>>> {
  return apiClient.get<Array<{ date: string; cost: number; tokens: number }>>('/api/usage/cost/daily', { days })
}

/** 获取使用记录列表 */
export async function getUsageRecords(params?: {
  provider?: string
  model_name?: string
  start_date?: string
  end_date?: string
  limit?: number
}): Promise<ApiResponse<{ records: UsageRecord[]; total: number }>> {
  return apiClient.get<{ records: UsageRecord[]; total: number }>('/api/usage/records', params ?? {})
}
