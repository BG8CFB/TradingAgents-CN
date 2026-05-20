/**
 * A 股数据管理 API
 */

import request from './request'

// ── 类型定义 ──

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

export interface FreshnessStatus {
  symbol: string
  domains: Record<string, string>
}

export interface CapabilityMatrix {
  [domain: string]: {
    [source: string]: string
  }
}

// ── Dashboard ──

export function getDashboard() {
  return request.get<DashboardData>('/cn/data/dashboard')
}

// ── Sync ──

export function triggerSync(domain: string, mode = 'incremental', symbols?: string[]) {
  return request.post(`/cn/data/sync/${domain}`, { domain, mode, symbols })
}

export function getSyncStatus(params: { page?: number; page_size?: number; domain?: string }) {
  return request.get<PaginatedResult<SyncCheckpoint>>('/cn/data/sync/status', { params })
}

export function getSyncEvents(params: { page?: number; page_size?: number; domain?: string; event_type?: string }) {
  return request.get<PaginatedResult<SyncEvent>>('/cn/data/sync/events', { params })
}

// ── Refresh ──

export function refreshStock(symbol: string, domains?: string[], force = false) {
  return request.post<RefreshResult>(`/cn/data/refresh/${symbol}`, { domains, force })
}

export function getRefreshStatus(symbol: string) {
  return request.get<FreshnessStatus>(`/cn/data/refresh/${symbol}/status`)
}

// ── Source Health ──

export function getSourceHealth() {
  return request.get<SourceHealthItem[]>('/cn/data/source-health')
}

export function resetCircuitBreaker(source: string, domain: string) {
  return request.post(`/cn/data/source-health/${source}/${domain}/reset`)
}

// ── Source Config ──

export function getSourceConfig() {
  return request.get<{ capability_matrix: CapabilityMatrix; priorities: Record<string, string[]> }>('/cn/data/source-config')
}

export function updateSourcePriority(domain: string, priority: string[]) {
  return request.put(`/cn/data/source-config/${domain}`, { priority })
}

// ── Data Viewer ──

export function getStockData(symbol: string, params?: { domain?: string; start_date?: string; end_date?: string; page?: number; page_size?: number }) {
  return request.get(`/cn/data/stock/${symbol}`, { params })
}

// ── Data Quality ──

export function getQualityOverview() {
  return request.get('/cn/data/quality/overview')
}

export function triggerQualityCheck(domain?: string) {
  return request.post('/cn/data/quality/check', null, { params: domain ? { domain } : {} })
}
