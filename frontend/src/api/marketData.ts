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
  success_rate_1h: number | null
  avg_latency_1h: number | null
  total_calls: number
  consecutive_failures: number
  open_count?: number
}

/** 域健康状态（后端数据层判定，前端只渲染） */
export type DomainHealthStatus =
  | 'healthy'
  | 'degraded'
  | 'unhealthy'
  | 'stale'
  | 'no_data'
  | 'unknown'

export interface DomainHealth {
  domain: string
  status: DomainHealthStatus
  reason: string
  record_count: number
  coverage: number | null
  last_sync_time: string | null
  freshness: {
    expected_hours: number | null
    actual_hours: number | null
    budget_hours: number | null
  }
  sources: Array<{
    source: string
    circuit_state: string
    success_rate_1h: number | null
    avg_latency_1h: number | null
    total_calls: number
    consecutive_failures: number
  }>
}

export type MarketOverall = 'all_healthy' | 'degraded' | 'partial_outage' | 'unknown'

export interface DashboardData {
  domain_stats: Record<string, DomainStat>
  domain_health: DomainHealth[]
  source_health: SourceHealthItem[]
  summary: {
    overall: MarketOverall
    total_domains: number
    healthy_domains: number
    warning_domains: number
    problem_domains: number
    unknown_domains: number
    degraded_fields?: string[]
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

/** 调度监控的运行中任务快照（内存态，进程重启后为空） */
export interface RunningSyncTask {
  task_id: string
  market?: string
  domain?: string
  started_at?: string
  elapsed_ms?: number
  is_timeout?: boolean
}

/** POST /sync/{domain} 响应：后台执行立即返回的触发标识 */
export interface SyncTriggerResult {
  market: string
  domain: string
  task_id: string
  job_id?: string
  mode: string
  status: 'triggered' | 'already_running' | 'failed'
  triggered: boolean
}

/** GET /sync/status 响应：分页检查点 + 运行中任务快照 */
export interface SyncStatusResult extends PaginatedResult<SyncCheckpoint> {
  running: RunningSyncTask[]
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
  intraday_quotes: '分时行情',
  money_flow: '资金流向',
  margin_trading: '融资融券',
  dragon_tiger: '龙虎榜',
  block_trade: '大宗交易',
  connect_status: '互联互通',
  southbound_holding: '南向持股',
  pre_post_market: '盘前盘后',
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
  return ApiClient.post<SyncTriggerResult>(`${base(market)}/sync/${domain}`, { domain, mode })
}

export function getSyncStatus(market: MarketCode, params: { page?: number; page_size?: number; domain?: string; trigger?: string }) {
  return ApiClient.get<SyncStatusResult>(`${base(market)}/sync/status`, params)
}

export function getSyncEvents(market: MarketCode, params: { page?: number; page_size?: number; domain?: string; event_type?: string }) {
  return ApiClient.get<PaginatedResult<SyncEvent>>(`${base(market)}/sync/events`, params)
}

// ── Stock Data ──

export function getStockData(market: MarketCode, symbol: string, params?: { domain?: string; start_date?: string; end_date?: string; page?: number; page_size?: number }) {
  return ApiClient.get(`${base(market)}/stock/${symbol}`, params)
}

// ── Data Quality ──

export function getQualityOverview(market: MarketCode) {
  return ApiClient.get(`${base(market)}/quality/overview`)
}
