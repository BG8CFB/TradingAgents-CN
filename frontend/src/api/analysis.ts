
/**
 * 股票分析API
 */

import { request, type ApiResponse } from './request'

// 后端期望的请求格式
export interface SingleAnalysisRequest {
  symbol?: string  // 主字段：6位股票代码
  stock_code?: string  // 兼容字段（已废弃）
  parameters?: {
    market_type?: string
    analysis_date?: string
    selected_analysts?: string[]
    custom_prompt?: string
    include_sentiment?: boolean
    include_risk?: boolean
    language?: string
    analyst_model?: string
    debate_model?: string
    mcp_tools?: string[]
  }
}

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

export interface AnalysisResult {
  analysis_id: string
  symbol?: string  // 主字段：6位股票代码
  stock_symbol: string  // 兼容字段
  stock_code?: string  // 兼容字段（已废弃）
  stock_name: string
  market_type: string
  analysis_date: string
  analysis_type: string

  // 基础数据
  current_price: number
  price_change: number
  price_change_percent: number
  volume: number
  market_cap?: number

  // 分析结果
  summary: string
  technical_analysis: string
  fundamental_analysis: string
  sentiment_analysis: string
  news_analysis?: string
  recommendation: string
  risk_assessment: string

  // 评分
  technical_score: number
  fundamental_score: number
  sentiment_score: number
  overall_score: number

  // 元数据
  data_sources: string[]
  llm_provider: string
  llm_model: string
  analysis_duration: number
  token_usage?: {
    prompt_tokens: number
    completion_tokens: number
    total_tokens: number
    cost: number
  }

  created_at: string
  updated_at: string
}

/** 分析过程事件（agent 执行时间线的单条事件，来自 WS /api/analysis/ws/task/{task_id} 或事件回放接口） */
export interface AgentEvent {
  task_id?: string
  seq: number
  ts?: number | string
  phase?: string
  agent_key: string
  event_type:
    | 'agent_start'
    | 'agent_end'
    | 'llm_request'
    | 'llm_response'
    | 'tool_call'
    | 'tool_result'
    | 'compact'
    | 'user_message_injected'
    | 'text_delta'
    | 'thinking'
    | 'thinking_delta'
    | 'status'
    | string
  payload?: Record<string, unknown>
}

/** 任务详情页聚合信息（GET /tasks/{id}/overview） */
export interface TaskOverview {
  task: {
    task_id: string
    status: string
    symbol?: string
    market_type?: string
    parameters?: Record<string, unknown>
    created_at?: string
    started_at?: string
    completed_at?: string
  }
  stock_info: {
    symbol: string
    name?: string | null
    market?: string
    industry?: string | null
    latest_price?: number | null
  } | null
}

/** 任务列表中的单个任务项（精简，仅前端消费字段） */
export interface AnalysisTask {
  task_id: string
  status: string
  symbol?: string
  stock_symbol?: string
  stock_code?: string
  stock_name?: string
  market_type?: string
  progress?: number
  current_step?: string
  message?: string
  error_message?: string
  created_at?: string
  updated_at?: string
  parameters?: Record<string, unknown>
  result_data?: unknown
}

export interface AnalysisHistory {
  total: number
  page: number
  page_size: number
  analyses: AnalysisResult[]
}

// 股票分析API
export const analysisApi = {
  // 开始单股分析（使用后端期望的格式）
  startSingleAnalysis(analysisRequest: SingleAnalysisRequest): Promise<ApiResponse<{ task_id: string; message: string }>> {
    return request.post('/api/analysis/single', analysisRequest)
  },

  // 获取任务状态
  getTaskStatus(taskId: string): Promise<ApiResponse<{
    status: string
    progress?: number
    progress_percentage?: number
    current_step_name?: string
    message?: string
    result_data?: any
    error_message?: string
  }>> {
    return request.get(`/api/analysis/tasks/${taskId}/status`)
  },

  // 获取分析历史（用户维度）
  getHistory(params?: {
    page?: number
    page_size?: number
    market_type?: string
    symbol?: string  // 主字段：股票代码
    stock_code?: string  // 兼容字段（已废弃）
    start_date?: string
    end_date?: string
    status?: string
  }): Promise<ApiResponse<{ tasks: AnalysisTask[]; total: number; page: number; page_size: number }>> {
    return request.get('/api/analysis/user/history', { params })
  },

  // 批量分析（方案A：与单股一致的进程内执行）
  startBatchAnalysis(batchRequest: {
    title: string
    description?: string
    symbols?: string[]  // 主字段：股票代码列表
    stock_codes?: string[]  // 兼容字段（已废弃）
    parameters?: SingleAnalysisRequest['parameters']
  }): Promise<ApiResponse<{ batch_id: string; total_tasks: number; task_ids: string[]; mapping?: any[]; status: string }>>{
    return request.post('/api/analysis/batch', batchRequest)
  },

  // 获取任务列表（新版 simple service）
  getTaskList(params?: { status?: string; limit?: number; offset?: number }): Promise<any>{
    return request.get('/api/analysis/tasks', { params })
  },

  // 获取任务结果（新版 simple service）
  getTaskResult(taskId: string): Promise<ApiResponse<Record<string, unknown>>>{
    return request.get(`/api/analysis/tasks/${taskId}/result`)
  },

  // 获取任务分析过程事件（回放用，支持按 agent/类型过滤、增量/向前分页拉取）
  getTaskEvents(taskId: string, params?: {
    agent_key?: string
    event_type?: string
    after_seq?: number
    before_seq?: number
    order?: 'asc' | 'desc'
    limit?: number
  }): Promise<ApiResponse<AgentEvent[]>> {
    return request.get(`/api/analysis/tasks/${taskId}/events`, { params })
  },

  // 获取任务详情页聚合信息（任务 + 股票信息）
  getTaskOverview(taskId: string): Promise<ApiResponse<TaskOverview>> {
    return request.get(`/api/analysis/tasks/${taskId}/overview`)
  },

  // 取消任务
  cancelTask(taskId: string): Promise<ApiResponse<{ success: boolean; message: string }>> {
    return request.post(`/api/analysis/tasks/${taskId}/cancel`, {})
  },

  // 标记任务为失败
  markTaskAsFailed(taskId: string): Promise<{ success: boolean; message: string }> {
    return request.post(`/api/analysis/tasks/${taskId}/mark-failed`, {})
  },

  // 删除任务
  deleteTask(taskId: string): Promise<{ success: boolean; message: string }> {
    return request.delete(`/api/analysis/tasks/${taskId}`)
  },

  // 搜索股票
  searchStocks(query: string, market?: string): Promise<Array<{
    symbol: string
    name: string
    market: string
    type: string
  }>> {
    return request.get('/api/analysis/search', {
      params: { query, market }
    })
  },

  // 获取分析统计
  getAnalysisStats(params?: {
    start_date?: string
    end_date?: string
    market_type?: string
  }): Promise<{
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
  }> {
    return request.get('/api/analysis/stats', { params })
  }
}
