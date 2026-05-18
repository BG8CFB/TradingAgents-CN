/**
 * 多数据源同步相关API
 */
import { ApiClient } from './request'
import type { ApiResponse } from './request'

// ==================== A股 类型定义 ====================

// 数据源状态接口
export interface DataSourceStatus {
  name: string
  priority: number
  available: boolean
  description: string
  token_source?: 'database' | 'env'  // Token 来源（仅 Tushare）
}

// 同步状态接口
export interface SyncStatus {
  job: string
  status: 'idle' | 'running' | 'success' | 'success_with_errors' | 'failed' | 'never_run'
  started_at?: string
  finished_at?: string
  total: number
  inserted: number
  updated: number
  errors: number
  last_trade_date?: string
  data_sources_used: string[]
  source_stats?: Record<string, Record<string, number>>
  message?: string
}

// 同步请求参数
export interface SyncRequest {
  force?: boolean
  preferred_sources?: string[]
}

// 基础测试结果接口
export interface BaseTestResult {
  success: boolean
  message: string
  count?: number
  date?: string
}

// 测试结果接口（简化版）
export interface DataSourceTestResult {
  name: string
  priority: number
  available: boolean
  message: string
  token_source?: 'database' | 'env'  // Token 来源（仅 Tushare）
}

// 使用建议接口
export interface SyncRecommendations {
  primary_source?: {
    name: string
    priority: number
    reason: string
  }
  fallback_sources: Array<{
    name: string
    priority: number
  }>
  suggestions: string[]
  warnings: string[]
}

// ==================== 港股/美股 类型定义 ====================

// 数据源状态（增强版，含优先级和描述）
export interface MarketSourceStatusEnhanced {
  name: string
  available: boolean
  priority: number
  description: string
}

// 缓存列表项
export interface CachedStockItem {
  symbol: string
  name?: string
  data_source: string
  updated_at: string
}

// 缓存统计
export interface MarketCacheStats {
  market: string
  cache_hours?: number
  available_sources?: string[]
  collection?: string
  cached_symbols?: number
  total_documents?: number
  valid_documents?: number
  expired_documents?: number
  last_updated?: string
  latest_symbol?: string
}

// 旧版兼容（不含增强字段）
export interface MarketSourceStatus {
  name: string
  available: boolean
}

// 批量预热任务状态
export interface WarmTaskStatus {
  task_id?: string
  status: 'idle' | 'running' | 'completed'
  total: number
  completed: number
  failed: number
  results?: Array<{
    symbol: string
    success: boolean
    message: string
  }>
}

// 市场使用建议
export interface MarketRecommendations {
  primary_source?: {
    name: string
    priority: number
    reason: string
  }
  fallback_sources: Array<{
    name: string
    priority: number
  }>
  suggestions: string[]
  warnings: string[]
  env_config?: {
    description: string
    example?: string
  }
}

// ==================== A股 API ====================

/**
 * 获取数据源状态
 */
export const getDataSourcesStatus = (): Promise<ApiResponse<DataSourceStatus[]>> => {
  return ApiClient.get('/api/multi-source-sync/sources/status')
}

/**
 * 获取当前正在使用的数据源
 */
export const getCurrentDataSource = (): Promise<ApiResponse<{
  name: string
  priority: number
  description: string
  token_source?: 'database' | 'env'
  token_source_display?: string
}>> => {
  return ApiClient.get('/api/multi-source-sync/sources/current')
}

/**
 * 获取同步状态
 */
export const getSyncStatus = (): Promise<ApiResponse<SyncStatus>> => {
  return ApiClient.get('/api/multi-source-sync/status')
}

/**
 * 运行股票基础信息同步
 */
export const runStockBasicsSync = (params?: {
  force?: boolean
  preferred_sources?: string
}): Promise<ApiResponse<SyncStatus>> => {
  const queryParams = new URLSearchParams()
  if (params?.force) {
    queryParams.append('force', 'true')
  }
  if (params?.preferred_sources) {
    queryParams.append('preferred_sources', params.preferred_sources)
  }

  const url = `/api/multi-source-sync/stock_basics/run${queryParams.toString() ? '?' + queryParams.toString() : ''}`
  return ApiClient.post(url, undefined, {
    timeout: 600000
  })
}

/**
 * 测试数据源连接
 * @param sourceName - 可选，指定要测试的数据源名称。如果不指定，则测试所有数据源
 */
export const testDataSources = (sourceName?: string): Promise<ApiResponse<{ test_results: DataSourceTestResult[] }>> => {
  const params = sourceName ? { source_name: sourceName } : {}
  return ApiClient.post('/api/multi-source-sync/test-sources', params, {
    timeout: 15000
  })
}

/**
 * 获取同步建议
 */
export const getSyncRecommendations = (): Promise<ApiResponse<SyncRecommendations>> => {
  return ApiClient.get('/api/multi-source-sync/recommendations')
}

/**
 * 获取同步历史记录
 */
export const getSyncHistory = (params?: {
  page?: number
  page_size?: number
  status?: string
}): Promise<ApiResponse<{
  records: SyncStatus[]
  total: number
  page: number
  page_size: number
  has_more: boolean
}>> => {
  const queryParams = new URLSearchParams()
  if (params?.page) {
    queryParams.append('page', params.page.toString())
  }
  if (params?.page_size) {
    queryParams.append('page_size', params.page_size.toString())
  }
  if (params?.status) {
    queryParams.append('status', params.status)
  }

  const url = `/api/multi-source-sync/history${queryParams.toString() ? '?' + queryParams.toString() : ''}`
  return ApiClient.get(url)
}

/**
 * 清空同步缓存
 */
export const clearSyncCache = (): Promise<ApiResponse<{ cleared: boolean }>> => {
  return ApiClient.delete('/api/multi-source-sync/cache')
}

// ==================== 港股/美股 旧版兼容 API ====================

/** @deprecated 使用 getMarketSourcesStatus 代替 */
export const getHKSourcesStatus = (): Promise<ApiResponse<MarketSourceStatus[]>> => {
  return ApiClient.get('/api/sync/hk/sources/status')
}

/** @deprecated 使用 getMarketCacheStats 代替 */
export const getHKCacheStats = (): Promise<ApiResponse<MarketCacheStats>> => {
  return ApiClient.get('/api/sync/hk/cache/stats')
}

/** @deprecated 使用 warmMarketCache 代替 */
export const warmHKCache = (symbol: string, force = false): Promise<ApiResponse<any>> => {
  return ApiClient.post('/api/sync/hk/cache/warm', { symbol, force })
}

/** @deprecated 使用 clearMarketCache 代替 */
export const clearHKCache = (): Promise<ApiResponse<any>> => {
  return ApiClient.delete('/api/sync/hk/cache')
}

/** @deprecated 使用 getMarketSourcesStatus 代替 */
export const getUSSourcesStatus = (): Promise<ApiResponse<MarketSourceStatus[]>> => {
  return ApiClient.get('/api/sync/us/sources/status')
}

/** @deprecated 使用 getMarketCacheStats 代替 */
export const getUSCacheStats = (): Promise<ApiResponse<MarketCacheStats>> => {
  return ApiClient.get('/api/sync/us/cache/stats')
}

/** @deprecated 使用 warmMarketCache 代替 */
export const warmUSCache = (symbol: string, force = false): Promise<ApiResponse<any>> => {
  return ApiClient.post('/api/sync/us/cache/warm', { symbol, force })
}

/** @deprecated 使用 clearMarketCache 代替 */
export const clearUSCache = (): Promise<ApiResponse<any>> => {
  return ApiClient.delete('/api/sync/us/cache')
}

// ==================== 港股/美股 统一 API ====================

const MARKET_API_MAP = {
  HK: '/api/sync/hk',
  US: '/api/sync/us',
} as const

export type MarketType = 'HK' | 'US'

/**
 * 获取数据源状态（增强版，含优先级和描述）
 */
export const getMarketSourcesStatus = (market: MarketType): Promise<ApiResponse<MarketSourceStatusEnhanced[]>> => {
  return ApiClient.get(`${MARKET_API_MAP[market]}/sources/status`)
}

/**
 * 测试数据源连通性
 */
export const testMarketSources = (
  market: MarketType,
  sourceName?: string,
): Promise<ApiResponse<{ test_results: DataSourceTestResult[] }>> => {
  return ApiClient.post(`${MARKET_API_MAP[market]}/sources/test`, {
    source_name: sourceName || null,
  }, {
    timeout: 30000,
  })
}

/**
 * 获取缓存统计
 */
export const getMarketCacheStats = (market: MarketType): Promise<ApiResponse<MarketCacheStats>> => {
  return ApiClient.get(`${MARKET_API_MAP[market]}/cache/stats`)
}

/**
 * 获取已缓存股票列表
 */
export const getMarketCacheList = (
  market: MarketType,
  page = 1,
  pageSize = 20,
): Promise<ApiResponse<{
  records: CachedStockItem[]
  total: number
  page: number
  page_size: number
  has_more: boolean
}>> => {
  return ApiClient.get(`${MARKET_API_MAP[market]}/cache/list`, {
    params: { page, page_size: pageSize },
  })
}

/**
 * 单股缓存预热（基础信息+行情）
 */
export const warmMarketCache = (
  market: MarketType,
  symbol: string,
  force = false,
): Promise<ApiResponse<{
  symbol: string
  info_success: boolean
  quotes_count: number
  source: string
}>> => {
  return ApiClient.post(`${MARKET_API_MAP[market]}/cache/warm`, {
    symbol,
    force,
  }, {
    timeout: 120000,
  })
}

/**
 * 批量缓存预热（后台执行）
 */
export const warmMarketCacheBatch = (
  market: MarketType,
  symbols: string[],
  force = false,
): Promise<ApiResponse<{
  task_id: string
  total: number
}>> => {
  return ApiClient.post(`${MARKET_API_MAP[market]}/cache/warm/batch`, {
    symbols,
    force,
  })
}

/**
 * 查询批量预热进度
 */
export const getMarketCacheWarmStatus = (market: MarketType): Promise<ApiResponse<WarmTaskStatus>> => {
  return ApiClient.get(`${MARKET_API_MAP[market]}/cache/warm/status`)
}

/**
 * 清理过期缓存
 */
export const clearMarketCache = (market: MarketType): Promise<ApiResponse<{
  market: string
  deleted_count: number
}>> => {
  return ApiClient.delete(`${MARKET_API_MAP[market]}/cache`)
}

/**
 * 获取市场使用建议
 */
export const getMarketRecommendations = (market: MarketType): Promise<ApiResponse<MarketRecommendations>> => {
  return ApiClient.get(`${MARKET_API_MAP[market]}/recommendations`)
}
