/**
 * 结算记分卡 API
 *
 * 契约说明：后端 GET /api/settlement/* 返回 ApiResponse<T>，
 * 页面代码统一用 res.data 取数；无记录时 success=true、data=null。
 */
import { ApiClient } from './request'
import type { ApiResponse, RequestConfig } from './request'

export interface CalibrationBucket {
  /** 桶标签："<60" | "60-70" | "70-80" | "80+" */
  bucket: string
  count: number
  avg_confidence: number
  hit_rate: number | null
}

export interface TrendPoint {
  /** 月份，形如 "2026-09" */
  month: string
  count: number
  hit_rate: number | null
  ci_low: number | null
  ci_high: number | null
  avg_return_pct: number | null
  /** 平均超额收益（仅基准可得样本），null=无样本 */
  avg_alpha_pct: number | null
}

export interface SignalStat {
  signal: string
  count: number
  hit_rate: number | null
  avg_return_pct: number | null
  avg_alpha_pct: number | null
}

/** 分期限统计（期限贯通）：pending 只计数不阅卷，hit_rate 仅以已结算样本为分母 */
export interface HorizonStat {
  /** 持有期交易日数（7/20/60；旧记录无期限字段时落 7 桶） */
  horizon_days: number
  count: number
  pending: number
  hit_rate: number | null
  avg_return_pct: number | null
}

export interface Scorecard {
  channel: string
  total_registered: number
  /** status=settled 且 signal 不为 Hold 的样本数 */
  settled_count: number
  pending_count: number
  unfillable_count: number
  hold_count: number
  /** 方向命中率，0-1 */
  hit_rate: number | null
  /** Wilson 95% 置信区间，0-1 */
  hit_ci: { low: number; high: number } | null
  avg_return_pct: number | null
  median_return_pct: number | null
  /** 平均超额收益（仅基准可得的样本） */
  avg_alpha_pct: number | null
  median_alpha_pct: number | null
  /** 跑赢基准比例（Buy: alpha>0 / Sell: alpha<0），0-1 */
  benchmark_hit_rate: number | null
  /** alpha 样本数（与命中率分母不同） */
  alpha_count: number
  calibration: CalibrationBucket[]
  trend: TrendPoint[]
  /** 无法成交占比，0-1 */
  unfillable_ratio: number | null
  by_signal: SignalStat[]
  by_horizon: HorizonStat[]
}

export type SettlementStatus = 'pending' | 'settled' | 'unfillable'

export interface SettlementRecord {
  task_id: string
  symbol: string
  stock_name: string | null
  market: string
  decision_date: string
  signal: string
  /** 陈述置信度，0-100 */
  stated_confidence: number | null
  status: SettlementStatus
  entry_date: string | null
  entry_price: number | null
  exit_date: string | null
  exit_price: number | null
  /** 百分数，2.35 表示 +2.35% */
  return_pct: number | null
  /** 基准指数规范码（如 000300.SH/HSI/SPX）；null=未结算或基准未解析 */
  benchmark_symbol: string | null
  /** 基准区间收益（百分数）；null=基准数据不可得 */
  benchmark_return_pct: number | null
  /** 超额收益 = return_pct - benchmark_return_pct；null=基准数据不可得 */
  alpha_pct: number | null
  /** 超额方向命中（Buy: alpha>0 / Sell: alpha<0）；null=不适用 */
  direction_hit_vs_benchmark: boolean | null
  /** null=不适用（Hold / 未结算） */
  direction_hit: boolean | null
  error_type: string | null
  failure_reason: string | null
  horizon_days: number
  channel: string
  settled_at: string | null
}

/** by-task 单条查询在 SettlementRecord 基础上附带派生字段 */
export interface SettlementRecordWithDays extends SettlementRecord {
  /** 待结算剩余交易日（仅 by-task 返回） */
  days_remaining: number | null
}

export interface SettlementRecordsPage {
  items: SettlementRecord[]
  total: number
  page: number
  page_size: number
}

/** 对象字面量类型（非 interface）：保持对 ApiClient.get params 的 Record 兼容 */
export type SettlementRecordsParams = {
  page?: number
  page_size?: number
  symbol?: string
  status?: SettlementStatus | string
  signal?: string
  error_type?: string
  channel?: string
  start_date?: string
  end_date?: string
  /** 持有期筛选（交易日数：7/20/60） */
  horizon_days?: number
}

/**
 * 获取结算记分卡汇总
 */
export function getSettlementScorecard(params?: {
  channel?: string
  symbol?: string
  months?: number
  /** 投资期限档位筛选（short/mid/long） */
  horizon?: string
}): Promise<ApiResponse<Scorecard>> {
  return ApiClient.get<Scorecard>('/api/settlement/scorecard', params)
}

/**
 * 分页查询结算记录
 */
export function getSettlementRecords(
  params?: SettlementRecordsParams
): Promise<ApiResponse<SettlementRecordsPage>> {
  return ApiClient.get<SettlementRecordsPage>('/api/settlement/records', params)
}

/**
 * 按任务 ID 查询结算记录（无记录时 data 为 null）
 */
export function getSettlementByTask(
  taskId: string,
  config?: RequestConfig
): Promise<ApiResponse<SettlementRecordWithDays | null>> {
  return ApiClient.get<SettlementRecordWithDays | null>(
    `/api/settlement/by-task/${taskId}`,
    undefined,
    config
  )
}
