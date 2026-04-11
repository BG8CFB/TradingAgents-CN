/**
 * 数据同步 API
 * 对应后端 app/routers/sync.py（前缀 /api/sync）和 multi_source_sync.py（前缀 /api/sync/multi-source）
 */

import apiClient from '../http/client'
import type { ApiResponse } from '@/types/common.types'

// ========== 基础同步 ==========

/** 触发股票基础数据全量同步 */
export async function runStockBasicsSync(force = false): Promise<ApiResponse<unknown>> {
  const url = force ? '/api/sync/stock_basics/run?force=true' : '/api/sync/stock_basics/run'
  return apiClient.post<unknown>(url)
}

/** 获取股票基础数据同步状态 */
export async function getStockBasicsStatus(): Promise<ApiResponse<unknown>> {
  return apiClient.get<unknown>('/api/sync/stock_basics/status')
}

// ========== 多数据源同步 ==========

export interface DataSourceStatusItem {
  name: string
  priority: number
  available: boolean
  description: string
  token_source?: string
}

/** 获取所有数据源状态 */
export async function getDataSourcesStatus(): Promise<ApiResponse<DataSourceStatusItem[]>> {
  return apiClient.get<DataSourceStatusItem[]>('/api/sync/multi-source/sources/status')
}

/** 获取当前使用的数据源 */
export async function getCurrentDataSource(): Promise<ApiResponse<{ name: string; priority: number; description: string }>> {
  return apiClient.get<{ name: string; priority: number; description: string }>(
    '/api/sync/multi-source/sources/current'
  )
}

/** 获取多数据源同步状态 */
export async function getMultiSourceSyncStatus(): Promise<ApiResponse<unknown>> {
  return apiClient.get<unknown>('/api/sync/multi-source/status')
}

/** 触发多数据源股票基础信息同步 */
export async function runMultiSourceSync(force = false, preferredSources?: string[]): Promise<ApiResponse<unknown>> {
  let url = `/api/sync/multi-source/stock_basics/run?force=${force}`
  if (preferredSources?.length) {
    url += `&preferred_sources=${preferredSources.join(',')}`
  }
  return apiClient.post<unknown>(url)
}

/** 测试数据源连通性 */
export async function testDataSources(sourceName?: string): Promise<ApiResponse<{
  test_results: Array<{
    name: string; priority: number; available: boolean; message: string
  }>
}>> {
  const body: Record<string, unknown> = {}
  if (sourceName) body.source_name = sourceName
  return apiClient.post<{
    test_results: Array<{
      name: string; priority: number; available: boolean; message: string
    }>
  }>('/api/sync/multi-source/test-sources', body)
}

/** 获取数据源使用建议 */
export async function getSyncRecommendations(): Promise<ApiResponse<{
  primary_source: { name: string; priority: number } | null
  fallback_sources: Array<{ name: string; priority: number }>
  suggestions: string[]
  warnings: string[]
}>> {
  return apiClient.get<{
    primary_source: { name: string; priority: number } | null
    fallback_sources: Array<{ name: string; priority: number }>
    suggestions: string[]
    warnings: string[]
  }>('/api/sync/multi-source/recommendations')
}

/** 获取同步历史记录 */
export async function getSyncHistory(page = 1, pageSize = 10, status?: string): Promise<ApiResponse<{
  records: Array<Record<string, unknown>>
  total: number
  page: number
  page_size: number
  has_more: boolean
}>> {
  const params: Record<string, unknown> = { page, page_size: pageSize }
  if (status) params.status = status
  return apiClient.get<{
    records: Array<Record<string, unknown>>
    total: number
    page: number
    page_size: number
    has_more: boolean
  }>('/api/sync/multi-source/history', params)
}
