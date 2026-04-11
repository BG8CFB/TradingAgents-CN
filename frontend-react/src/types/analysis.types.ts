/** 分析状态 */
export type AnalysisStatus =
  | 'pending'
  | 'processing'
  | 'completed'
  | 'failed'
  | 'cancelled'

/** 批次状态 */
export type BatchStatus =
  | 'pending'
  | 'processing'
  | 'completed'
  | 'partial_success'
  | 'failed'
  | 'cancelled'

/** 分析参数 */
export interface AnalysisParameters {
  market_type?: string
  analysis_date?: string
  research_depth?: string
  selected_analysts?: string[]
  custom_prompt?: string
  include_sentiment?: boolean
  include_risk?: boolean
  language?: string
  quick_analysis_model?: string
  deep_analysis_model?: string
  phase2_enabled?: boolean
  phase2_debate_rounds?: number
  phase3_enabled?: boolean
  phase3_debate_rounds?: number
  phase4_enabled?: boolean
  phase4_debate_rounds?: number
  mcp_enabled?: boolean
  mcp_tools?: string[]
  mcp_tool_ids?: string[]
}

/** 交易决策 */
export interface TradeDecision {
  action?: string
  target_price?: number
  confidence?: number
  stop_loss?: number
  position_size?: string
  time_horizon?: string
  reasoning?: string
}

/** 分析结果 */
export interface AnalysisResult {
  analysis_id: string
  stock_symbol: string
  stock_code?: string
  stock_name?: string
  analysis_date?: string
  summary: string
  recommendation: string
  confidence_score: number
  risk_level: string
  key_points: string[]
  detailed_analysis?: Record<string, unknown>
  charts: string[]
  tokens_used: number
  execution_time: number
  error_message?: string
  model_info?: string
  decision?: TradeDecision
  structured_summary?: Record<string, unknown>
  reports?: Record<string, string>
  analysts?: string[]
  research_depth?: string
  status?: AnalysisStatus
  created_at?: string
  updated_at?: string
}

/** 分析任务 */
export interface AnalysisTask {
  task_id: string
  batch_id?: string
  symbol: string
  stock_code?: string
  stock_name?: string
  status: AnalysisStatus
  progress: number
  created_at: string
  started_at?: string
  completed_at?: string
  parameters?: AnalysisParameters
  result?: AnalysisResult
  last_error?: string
  retry_count?: number
}

/** 分析批次 */
export interface AnalysisBatch {
  batch_id: string
  title: string
  description?: string
  status: BatchStatus
  total_tasks: number
  completed_tasks: number
  failed_tasks: number
  cancelled_tasks: number
  progress: number
  created_at: string
  completed_at?: string
  parameters?: AnalysisParameters
  results_summary?: Record<string, unknown>
}

/** 股票信息 */
export interface StockInfo {
  symbol: string
  code?: string
  name: string
  market: string
  industry?: string
  sector?: string
  market_cap?: number
  price?: number
  change_percent?: number
}

/** 单股分析请求 */
export interface SingleAnalysisRequest {
  symbol?: string
  stock_code?: string
  parameters?: AnalysisParameters
}

/** 批量分析请求 */
export interface BatchAnalysisRequest {
  title: string
  description?: string
  symbols?: string[]
  stock_codes?: string[]
  parameters?: AnalysisParameters
}

/** 任务状态数据（从 /tasks/{taskId}/status 返回） */
export interface TaskStatusData {
  task_id: string
  status: AnalysisStatus | string
  progress: number
  message?: string
  current_step?: string
  start_time?: string
  end_time?: string
  elapsed_time?: number
  remaining_time?: number
  estimated_total_time?: number
  symbol?: string
  stock_code?: string
  stock_symbol?: string
  stock_name?: string
  analysts?: string[]
  research_depth?: string
  source?: string
  error_message?: string
}

/** SSE 消息类型 */
export type SSEEventType = 'connected' | 'progress' | 'heartbeat' | 'error' | 'finished'

/** SSE 进度数据 */
export interface SSEProgressData {
  task_id?: string
  batch_id?: string
  status?: AnalysisStatus | string
  progress?: number
  message?: string
  current_step?: string
  step_detail?: string
  steps?: AnalysisStep[]
  elapsed_time?: number
  remaining_time?: number
  estimated_total_time?: number
  timestamp?: number
  error?: string
  final_status?: string
  total_tasks?: number
  completed?: number
  failed?: number
  processing?: number
}

/** SSE 消息 */
export interface SSEMessage {
  event: SSEEventType
  data: SSEProgressData | Record<string, unknown>
}

/** 分析步骤 */
export interface AnalysisStep {
  name: string
  title: string
  description: string
  status: 'pending' | 'active' | 'success' | 'error'
  started_at?: string
  completed_at?: string
  duration?: number
  error_message?: string
}

/** 分析历史查询参数 */
export interface AnalysisHistoryQuery {
  page?: number
  page_size?: number
  symbol?: string
  stock_code?: string
  status?: string
  start_date?: string
  end_date?: string
  market_type?: string
}

/** 分析统计 */
export interface AnalysisStats {
  total_analyses: number
  successful_analyses: number
  failed_analyses: number
  avg_duration: number
  total_tokens: number
  total_cost: number
  popular_stocks: Array<{
    symbol: string
    name: string
    count: number
  }>
  analysis_by_date: Array<{
    date: string
    count: number
  }>
  analysis_by_market: Array<{
    market: string
    count: number
  }>
}

/** 用户队列状态 */
export interface QueueStatus {
  pending: number
  processing: number
  completed: number
  failed: number
  total: number
  max_concurrent: number
  current_processing: number
}

/** 僵尸任务 */
export interface ZombieTask {
  task_id: string
  symbol?: string
  status: string
  progress: number
  created_at?: string
  started_at?: string
  elapsed_hours: number
}

/** 热门股票 */
export interface PopularStock {
  symbol: string
  name: string
  market: string
  current_price: number
  change_percent: number
  volume: number
  analysis_count: number
}

/** 搜索结果股票 */
export interface SearchedStock {
  symbol: string
  name: string
  market: string
  type: string
}

/** 单股分析响应 */
export interface SingleAnalysisResponse {
  task_id: string
  analysis_id?: string
  status: AnalysisStatus
  message?: string
}

/** 批量分析响应 */
export interface BatchAnalysisResponse {
  batch_id: string
  total_tasks: number
  task_ids: string[]
  mapping: Array<{ symbol: string; stock_code: string; task_id: string }>
  status: string
}

/** 任务列表响应 */
export interface TaskListResponse {
  tasks: AnalysisTask[]
  total: number
  limit: number
  offset: number
}
