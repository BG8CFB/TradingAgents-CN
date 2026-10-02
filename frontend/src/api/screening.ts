import { ApiClient } from './request'

export interface ScreeningOrderBy { field: string; direction: 'asc' | 'desc' }
export interface ScreeningRunReq {
  market?: 'CN'
  date?: string | null
  adj?: 'qfq' | 'hfq' | 'none'
  conditions: any
  order_by?: ScreeningOrderBy[]
  limit?: number
  offset?: number
}

export interface ScreeningRunItem {
  code: string
  close?: number
  pct_chg?: number
  amount?: number
  ma20?: number
  rsi14?: number
  kdj_k?: number
  kdj_d?: number
  kdj_j?: number
  dif?: number
  dea?: number
  macd_hist?: number
}

export interface ScreeningRunResp { total: number; items: ScreeningRunItem[] }

// ── L0 策略选股（/run?strategy_id 路径 + /strategies + /daily）──

export interface StrategyInfo {
  id: string
  name: string
  description: string
  style: 'short_term' | 'balanced' | 'value'
  top_n: number
  is_default: boolean
  filters: Array<{ field: string; op: string; value: any }>
}

export interface StrategySignalItem {
  field: string
  op: string
  value: number | [number, number]
}

export interface StrategyRunItem {
  symbol: string
  code: string
  name?: string | null
  industry?: string | null
  score?: number | null
  score_short_term?: number | null
  score_balanced?: number | null
  score_value?: number | null
  factors: Record<string, number>
  signals: string[]
  /** 结构化入选信号（新后端返回；用于中文化渲染，缺省时回退 signals 英文串） */
  signal_items?: StrategySignalItem[]
  insight?: string | null
}

export interface StrategyRunResp {
  total: number
  items: StrategyRunItem[]
  as_of: string | null
  strategy: string
  style: StrategyInfo['style']
}

export interface DailyStrategyEntry {
  strategy_id: string
  strategy_name?: string | null
  style?: StrategyInfo['style'] | null
  total?: number
  items: StrategyRunItem[]
  insight_status?: string | null
  generated_at?: string | null
}

export interface DailyResp {
  trade_date: string | null
  strategies: DailyStrategyEntry[]
}

// ── L1 快速研判 ──

export interface InsightResp {
  insights: Record<string, string>
  trade_date: string | null
  quota_remaining: number
}

export interface InsightQuotaResp { quota_remaining: number }

// 筛选字段配置
export interface FieldInfo {
  name: string
  display_name: string
  field_type: string
  data_type: string
  description: string
  supported_operators: string[]
}

export interface FieldConfigResponse {
  fields: Record<string, FieldInfo>
  categories: Record<string, string[]>
}

// 行业列表响应
export interface IndustryOption {
  value: string
  label: string
  count: number
}

export interface IndustriesResponse {
  industries: IndustryOption[]
  total: number
}

export const screeningApi = {
  run: (payload: ScreeningRunReq, options?: { timeout?: number }) =>
    ApiClient.post<ScreeningRunResp>('/api/screening/run', payload, { timeout: options?.timeout ?? 120000 }),
  getFields: () => ApiClient.get<FieldConfigResponse>('/api/screening/fields'),
  getIndustries: () => ApiClient.get<IndustriesResponse>('/api/screening/industries'),
  // L0 策略选股
  getStrategies: () =>
    ApiClient.get<{ strategies: StrategyInfo[] }>('/api/screening/strategies'),
  runStrategy: (strategyId: string, limit?: number, conditions?: any) =>
    ApiClient.post<StrategyRunResp>('/api/screening/run', {
      strategy_id: strategyId,
      conditions: conditions ?? {},
      limit: limit ?? 30
    }),
  getDaily: (strategyId?: string) =>
    ApiClient.get<DailyResp>('/api/screening/daily',
      strategyId ? { strategy_id: strategyId } : undefined),
  // L1 快速研判（消耗 token，用户显式触发）
  postInsights: (symbols: string[], strategyId?: string, conditionsDigest?: string) =>
    ApiClient.post<InsightResp>('/api/screening/insights', {
      symbols,
      strategy_id: strategyId ?? null,
      conditions_digest: conditionsDigest ?? null
    }),
  getInsightQuota: () =>
    ApiClient.get<InsightQuotaResp>('/api/screening/insights/quota')
}

