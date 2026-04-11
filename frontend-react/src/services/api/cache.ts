/**
 * 缓存管理 API
 * 对应后端 app/routers/cache.py（前缀 /api/cache）
 */

import apiClient from '../http/client'
import type { ApiResponse } from '@/types/common.types'

export interface CacheStats {
  totalFiles: number
  totalSize: number
  maxSize: number
  stockDataCount: number
  newsDataCount: number
  analysisDataCount: number
}

export interface CacheDetails {
  items: unknown[]
  total: number
  page: number
  page_size: number
}

export interface CacheBackendInfo {
  system: string
  primary_backend: string
  fallback_enabled: boolean
}

/** 获取缓存统计 */
export async function getCacheStats(): Promise<ApiResponse<CacheStats>> {
  return apiClient.get<CacheStats>('/api/cache/stats')
}

/** 清理过期缓存 */
export async function cleanupCache(days = 7): Promise<ApiResponse<Record<string, never>>> {
  return apiClient.delete<Record<string, never>>(`/api/cache/cleanup?days=${days}`)
}

/** 清空所有缓存 */
export async function clearAllCache(): Promise<ApiResponse<Record<string, never>>> {
  return apiClient.delete<Record<string, never>>('/api/cache/clear')
}

/** 获取缓存详情列表 */
export async function getCacheDetails(page = 1, pageSize = 20): Promise<ApiResponse<CacheDetails>> {
  return apiClient.get<CacheDetails>('/api/cache/details', { page, page_size: pageSize })
}

/** 获取缓存后端信息 */
export async function getCacheBackendInfo(): Promise<ApiResponse<CacheBackendInfo>> {
  return apiClient.get<CacheBackendInfo>('/api/cache/backend-info')
}
