import apiClient from '../http/client'
import type { ApiResponse, RequestConfig } from '@/types/common.types'

export interface ReportItem {
  id: string
  analysis_id: string
  title: string
  stock_code: string
  stock_name: string
  market_type: string
  model_info: string
  type: string
  format: string
  status: string
  created_at: string
  analysis_date: string
  analysts: string[]
  research_depth: number
  summary: string
  file_size: number
  source: string
  task_id: string
}

export interface ReportDetail {
  id: string
  analysis_id: string
  stock_symbol: string
  stock_name: string
  model_info: string
  analysis_date: string
  status: string
  created_at: string
  updated_at: string
  analysts: string[]
  research_depth: number
  summary: string
  reports: Record<string, string>
  source: string
  task_id: string
  recommendation: string
  confidence_score: number
  risk_level: string
  key_points: string[]
  execution_time: number
  tokens_used: number
  decision: Record<string, unknown>
}

export interface ReportListParams {
  page?: number
  page_size?: number
  search_keyword?: string
  market_filter?: string
  start_date?: string
  end_date?: string
  stock_code?: string
}

export interface ReportListResponse {
  reports: ReportItem[]
  total: number
  page: number
  page_size: number
}

/** 获取报告列表 */
export async function getReportList(params: ReportListParams = {}, config?: RequestConfig): Promise<ApiResponse<ReportListResponse>> {
  return apiClient.get<ReportListResponse>('/api/reports/list', params as unknown as Record<string, unknown>, config)
}

/** 获取报告详情 */
export async function getReportDetail(reportId: string): Promise<ApiResponse<ReportDetail>> {
  return apiClient.get<ReportDetail>(`/api/reports/${reportId}/detail`)
}

/** 获取报告模块内容 */
export async function getReportModuleContent(reportId: string, module: string): Promise<ApiResponse<unknown>> {
  return apiClient.get<unknown>(`/api/reports/${reportId}/content/${module}`)
}

/** 删除报告 */
export async function deleteReport(reportId: string): Promise<ApiResponse<unknown>> {
  return apiClient.delete<unknown>(`/api/reports/${reportId}`)
}

/** 下载报告 */
export function getReportDownloadUrl(reportId: string, format: 'markdown' | 'json' | 'pdf' | 'docx' = 'markdown') {
  return `/api/reports/${reportId}/download?format=${format}`
}
