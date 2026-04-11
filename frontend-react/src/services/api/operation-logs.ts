/**
 * 操作日志 API
 * 对应后端 app/routers/operation_logs.py（前缀 /api/system/logs）
 */

import apiClient from '../http/client'
import type { ApiResponse } from '@/types/common.types'

export interface OperationLogItem {
  id: string
  user_id: string
  username: string
  action_type: string
  action: string
  success: boolean
  duration_ms?: number
  ip_address?: string
  error_message?: string
  timestamp: string
  details?: Record<string, unknown>
}

export interface OperationLogListResponse {
  logs: OperationLogItem[]
  total: number
  page: number
  page_size: number
  total_pages: number
}

export interface OperationLogStats {
  total_count: number
  success_count: number
  failed_count: number
  by_action_type: Record<string, number>
  by_user: Record<string, number>
  daily_trend: Array<{ date: string; count: number }>
}

/** 获取操作日志列表 */
export async function getOperationLogs(params?: {
  page?: number; page_size?: number; start_date?: string;
  end_date?: string; action_type?: string; success?: boolean; keyword?: string
}): Promise<ApiResponse<OperationLogListResponse>> {
  return apiClient.get<OperationLogListResponse>('/api/system/logs/list', params ?? {})
}

/** 获取操作日志统计 */
export async function getOperationLogStats(days = 30): Promise<ApiResponse<OperationLogStats>> {
  return apiClient.get<OperationLogStats>('/api/system/logs/stats', { days })
}

/** 获取操作日志详情 */
export async function getOperationLogDetail(logId: string): Promise<ApiResponse<OperationLogItem>> {
  return apiClient.get<OperationLogItem>(`/api/system/logs/${logId}`)
}

/** 清空操作日志 */
export async function clearOperationLogs(days?: number, actionType?: string): Promise<ApiResponse<{ deleted_count: number }>> {
  const body: Record<string, unknown> = {}
  if (days !== undefined) body.days = days
  if (actionType) body.action_type = actionType
  return apiClient.post<{ deleted_count: number }>('/api/system/logs/clear', body)
}
