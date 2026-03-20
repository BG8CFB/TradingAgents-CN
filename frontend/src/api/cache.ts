/**
 * 缓存管理 API
 */
import { ApiClient } from './request'

/**
 * 缓存统计数据
 */
export interface CacheStats {
  totalFiles: number
  totalSize: number
  maxSize: number
  stockDataCount: number
  newsDataCount: number
  analysisDataCount: number
}

/**
 * 缓存详情项
 */
export interface CacheDetailItem {
  type: string
  symbol: string
  size: number
  created_at: string
  last_accessed: string
  hit_count: number
}

/**
 * 缓存详情响应
 */
export interface CacheDetailsResponse {
  items: CacheDetailItem[]
  total: number
  page: number
  page_size: number
}

/**
 * 缓存后端信息
 */
export interface CacheBackendInfo {
  system: string
  primary_backend: string
  fallback_enabled: boolean
  mongodb_available?: boolean
  redis_available?: boolean
}

/**
 * 获取缓存统计
 */
export function getCacheStats() {
  return ApiClient.get<CacheStats>('/api/cache/stats')
}

/**
 * 清理过期缓存
 * @param days 清理多少天前的缓存
 */
export function cleanupOldCache(days: number) {
  return ApiClient.delete('/api/cache/cleanup', { params: { days } })
}

/**
 * 清空所有缓存
 */
export function clearAllCache() {
  return ApiClient.delete('/api/cache/clear')
}

/**
 * 获取缓存详情列表
 * @param page 页码
 * @param pageSize 每页数量
 */
export function getCacheDetails(page: number = 1, pageSize: number = 20) {
  return ApiClient.get<CacheDetailsResponse>('/api/cache/details', { page, page_size: pageSize })
}

/**
 * 获取缓存后端信息
 */
export function getCacheBackendInfo() {
  return ApiClient.get<CacheBackendInfo>('/api/cache/backend-info')
}
