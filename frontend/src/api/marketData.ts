/**
 * 统一多市场数据管理 API
 *
 * CN / HK / US 三市场共享完全对等的后端端点：
 *   GET  /api/{market}/data/dashboard
 *   GET  /api/{market}/data/sources/health
 *   POST /api/{market}/data/sources/health/{source}/{domain}/reset
 *   GET  /api/{market}/data/source-config
 *   PUT  /api/{market}/data/config/priority/{domain}
 *   GET  /api/{market}/data/stock/{symbol}
 *   GET  /api/{market}/data/quality/overview
 *   POST /api/{market}/data/quality/check
 *   GET  /api/{market}/data/sync/status
 *   GET  /api/{market}/data/sync/events
 *   POST /api/{market}/data/sync/{domain}
 *   POST /api/{market}/data/refresh/{symbol}
 *   GET  /api/{market}/data/refresh/{symbol}/status
 */

import { ApiClient } from './request'

// ── 市场类型 ──

export type MarketCode = 'cn' | 'hk' | 'us'

const MARKET_PREFIX: Record<MarketCode, string> = {
  cn: '/api/cn/data',
  hk: '/api/hk/data',
  us: '/api/us/data',
}

function base(market: MarketCode): string {
  return MARKET_PREFIX[market]
}

// ── 通用类型 ──

export interface DomainStat {
  records: number
  last_updated: string | null
}

export interface SourceHealthItem {
  source: string
  domain: string
  circuit_state: string
  success_rate_1h: number
  avg_latency_1h: number
  total_calls: number
  consecutive_failures: number
  open_count: number
}

export interface DashboardData {
  domain_stats: Record<string, DomainStat>
  source_health: SourceHealthItem[]
  summary: {
    total_domains: number
    healthy_sources: number
  }
}

export interface SyncCheckpoint {
  domain: string
  source: string
  last_sync_date: string
  last_sync_time: string
  status: string
  record_count: number
  duration_ms: number
}

export interface SyncEvent {
  event_type: string
  domain: string
  source: string
  symbol: string | null
  record_count: number
  duration_ms: number
  error_message: string | null
  fallback_from: string | null
  updated_at: string
}

export interface PaginatedResult<T> {
  items: T[]
  total: number
  page: number
  page_size: number
}

export interface RefreshResult {
  symbol: string
  status: string
  domains: Record<string, {
    status: string
    source: string
    fallback_from: string | null
    records: number
    error: string | null
    latency_ms: number
  }>
  duration_ms: number
}

export interface CapabilityMatrix {
  [domain: string]: {
    [source: string]: string
  }
}

export interface DataSourceStatus {
  name: string
  priority: number
  available: boolean
  description: string
  token_source?: 'database' | 'env'
}

// ── 域名映射 ──

export const DOMAIN_LABELS: Record<string, string> = {
  basic_info: '基础信息',
  daily_quotes: '日K线',
  daily_indicators: '每日指标',
  adj_factors: '复权因子',
  financial_data: '财务数据',
  market_quotes: '实时行情',
  news: '新闻',
  trade_calendar: '交易日历',
  corporate_actions: '公司行为',
}

// ── Dashboard ──

export function getDashboard(market: MarketCode) {
  return ApiClient.get<DashboardData>(`${base(market)}/dashboard`)
}

// ── Source Health ──

export function getSourcesHealth(market: MarketCode) {
  return ApiClient.get<SourceHealthItem[]>(`${base(market)}/sources/health`)
}

export function resetCircuitBreaker(market: MarketCode, source: string, domain: string) {
  return ApiClient.post(`${base(market)}/sources/health/${source}/${domain}/reset`)
}

// ── Source Config ──

export function getSourceConfig(market: MarketCode) {
  return ApiClient.get<{ capability_matrix: CapabilityMatrix; priorities: Record<string, string[]> }>(`${base(market)}/source-config`)
}

export function updateSourcePriority(market: MarketCode, domain: string, priority: string[]) {
  return ApiClient.put(`${base(market)}/config/priority/${domain}`, { priority })
}

// ── Sync ──

export function triggerSync(market: MarketCode, domain: string, mode = 'incremental') {
  return ApiClient.post(`${base(market)}/sync/${domain}`, { domain, mode })
}

export function getSyncStatus(market: MarketCode, params: { page?: number; page_size?: number; domain?: string }) {
  return ApiClient.get<PaginatedResult<SyncCheckpoint>>(`${base(market)}/sync/status`, params)
}

export function getSyncEvents(market: MarketCode, params: { page?: number; page_size?: number; domain?: string; event_type?: string }) {
  return ApiClient.get<PaginatedResult<SyncEvent>>(`${base(market)}/sync/events`, params)
}

// ── Refresh ──

export function refreshStock(market: MarketCode, symbol: string, domains?: string[], force = false) {
  return ApiClient.post<RefreshResult>(`${base(market)}/refresh/${symbol}`, { domains, force })
}

export function getRefreshStatus(market: MarketCode, symbol: string) {
  return ApiClient.get(`${base(market)}/refresh/${symbol}/status`)
}

// ── Stock Data ──

export function getStockData(market: MarketCode, symbol: string, params?: { domain?: string; start_date?: string; end_date?: string; page?: number; page_size?: number }) {
  return ApiClient.get(`${base(market)}/stock/${symbol}`, params)
}

// ── Data Quality ──

export function getQualityOverview(market: MarketCode) {
  return ApiClient.get(`${base(market)}/quality/overview`)
}

export function triggerQualityCheck(market: MarketCode, domain?: string) {
  return ApiClient.post(`${base(market)}/quality/check`, null, { params: domain ? { domain } : {} })
}
