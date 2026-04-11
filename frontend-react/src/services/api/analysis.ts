import type { ApiResponse, PaginatedResponse } from '@/types/common.types'
import type {
  AnalysisResult,
  AnalysisTask,
  AnalysisBatch,
  StockInfo,
  SingleAnalysisRequest,
  BatchAnalysisRequest,
  TaskStatusData,
  AnalysisStats,
  QueueStatus,
  ZombieTask,
  PopularStock,
  SearchedStock,
  SingleAnalysisResponse,
  BatchAnalysisResponse,
  TaskListResponse,
} from '@/types/analysis.types'
import apiClient from '../http/client'

// Re-export types for convenience
export type { AnalysisStats, QueueStatus } from '@/types/analysis.types'

const BASE_URL = import.meta.env.VITE_API_BASE_URL || ''

/** 提交单股分析 */
export function submitSingleAnalysis(
  request: SingleAnalysisRequest
): Promise<ApiResponse<SingleAnalysisResponse>> {
  return apiClient.post('/api/analysis/single', request)
}

/** 提交批量分析 */
export function submitBatchAnalysis(
  request: BatchAnalysisRequest
): Promise<ApiResponse<BatchAnalysisResponse>> {
  return apiClient.post('/api/analysis/batch', request)
}

/** 获取任务状态 */
export function getTaskStatus(taskId: string): Promise<ApiResponse<TaskStatusData>> {
  return apiClient.get(`/api/analysis/tasks/${taskId}/status`)
}

/** 获取任务结果 */
export function getTaskResult(taskId: string): Promise<ApiResponse<AnalysisResult>> {
  return apiClient.get(`/api/analysis/tasks/${taskId}/result`)
}

/** 获取当前用户的任务列表 */
export function listUserTasks(params?: {
  status?: string
  limit?: number
  offset?: number
}): Promise<ApiResponse<TaskListResponse>> {
  return apiClient.get('/api/analysis/tasks', params)
}

/** 获取所有任务列表（管理员） */
export function listAllTasks(params?: {
  status?: string
  limit?: number
  offset?: number
}): Promise<ApiResponse<TaskListResponse>> {
  return apiClient.get('/api/analysis/tasks/all', params)
}

/** 取消任务 */
export function cancelTask(taskId: string): Promise<ApiResponse<{ success: boolean; message: string }>> {
  return apiClient.post(`/api/analysis/tasks/${taskId}/cancel`, {})
}

/** 将任务标记为失败 */
export function markTaskAsFailed(
  taskId: string
): Promise<ApiResponse<{ success: boolean; message: string }>> {
  return apiClient.post(`/api/analysis/tasks/${taskId}/mark-failed`, {})
}

/** 删除任务 */
export function deleteTask(taskId: string): Promise<ApiResponse<{ success: boolean; message: string }>> {
  return apiClient.delete(`/api/analysis/tasks/${taskId}`)
}

/** 获取用户分析历史 */
export function getUserHistory(params?: {
  page?: number
  page_size?: number
  status?: string
  start_date?: string
  end_date?: string
  symbol?: string
  stock_code?: string
  market_type?: string
}): Promise<ApiResponse<PaginatedResponse<AnalysisTask>>> {
  return apiClient.get('/api/analysis/user/history', params)
}

/** 获取用户队列状态 */
export function getUserQueueStatus(): Promise<ApiResponse<QueueStatus>> {
  return apiClient.get('/api/analysis/user/queue-status')
}

/** 获取分析统计 */
export function getAnalysisStats(params?: {
  start_date?: string
  end_date?: string
  market_type?: string
}): Promise<ApiResponse<AnalysisStats>> {
  return apiClient.get('/api/analysis/stats', params)
}

/** 获取股票基础信息 */
export function getStockInfo(
  symbol: string,
  market: string
): Promise<
  ApiResponse<
    StockInfo & {
      current_price?: number
      change?: number
      change_percent?: number
      volume?: number
      pe_ratio?: number
      pb_ratio?: number
      dividend_yield?: number
    }
  >
> {
  return apiClient.get('/api/analysis/stock-info', { symbol, market })
}

/** 搜索股票 */
export function searchStocks(query: string, market?: string): Promise<ApiResponse<SearchedStock[]>> {
  return apiClient.get('/api/analysis/search', { query, market })
}

/** 获取热门股票 */
export function getPopularStocks(market?: string, limit = 10): Promise<ApiResponse<PopularStock[]>> {
  return apiClient.get('/api/analysis/popular', { market, limit })
}

/** 获取批次详情 */
export function getBatch(batchId: string): Promise<ApiResponse<AnalysisBatch>> {
  return apiClient.get(`/api/analysis/batches/${batchId}`)
}

/** 获取任务详情 */
export function getTaskDetails(taskId: string): Promise<ApiResponse<Record<string, unknown>>> {
  return apiClient.get(`/api/analysis/tasks/${taskId}/details`)
}

/** 获取僵尸任务列表（管理员） */
export function getZombieTasks(maxRunningHours = 2): Promise<
  ApiResponse<{
    tasks: ZombieTask[]
    total: number
    max_running_hours: number
  }>
> {
  return apiClient.get('/api/analysis/admin/zombie-tasks', { max_running_hours: maxRunningHours })
}

/** 清理僵尸任务（管理员） */
export function cleanupZombieTasks(maxRunningHours = 2): Promise<
  ApiResponse<Record<string, unknown> & { total_cleaned: number }>
> {
  return apiClient.post(`/api/analysis/admin/cleanup-zombie-tasks?max_running_hours=${maxRunningHours}`, {})
}

/** 创建任务 SSE 连接 */
export function connectTaskSSE(taskId: string): EventSource {
  const url = `${BASE_URL}/api/stream/tasks/${taskId}`
  return new EventSource(url, { withCredentials: true })
}

/** 创建批次 SSE 连接 */
export function connectBatchSSE(batchId: string): EventSource {
  const url = `${BASE_URL}/api/stream/batches/${batchId}`
  return new EventSource(url, { withCredentials: true })
}

// ==================== 常量 ====================

export const MARKET_TYPES = {
  US: '美股',
  CN: 'A股',
  HK: '港股',
} as const

export const ANALYSIS_STATUS_LABELS: Record<string, string> = {
  pending: '待处理',
  processing: '进行中',
  completed: '已完成',
  failed: '失败',
  cancelled: '已取消',
} as const

export const BATCH_STATUS_LABELS: Record<string, string> = {
  pending: '待处理',
  processing: '进行中',
  completed: '已完成',
  partial_success: '部分成功',
  failed: '失败',
  cancelled: '已取消',
} as const

/** 获取股票代码占位提示 */
export function getStockPlaceholder(market: string): string {
  const placeholders: Record<string, string> = {
    '美股': '输入美股代码，如 AAPL, TSLA, MSFT',
    'A股': '输入A股代码，如 000001, 600519',
    '港股': '输入港股代码，如 0700.HK, 9988.HK',
  }
  return placeholders[market] ?? '输入股票代码'
}

/** 获取股票代码示例 */
export function getStockExamples(market: string): string[] {
  const examples: Record<string, string[]> = {
    '美股': ['AAPL', 'TSLA', 'MSFT', 'GOOGL', 'AMZN', 'META', 'NVDA', 'NFLX'],
    'A股': ['000001', '600519', '000002', '600036', '000858', '002415', '300059', '688981'],
    '港股': ['0700.HK', '9988.HK', '3690.HK', '0941.HK', '1810.HK', '2318.HK', '1299.HK'],
  }
  return examples[market] ?? []
}

/** 验证股票代码格式 */
export function validateStockSymbol(symbol: string, market: string): boolean {
  const s = symbol.trim().toUpperCase()
  switch (market) {
    case '美股':
      return /^[A-Z]{1,5}$/.test(s)
    case 'A股':
      return /^\d{6}$/.test(s)
    case '港股':
      return /^\d{4,5}\.HK$/.test(s)
    default:
      return s.length > 0
  }
}
