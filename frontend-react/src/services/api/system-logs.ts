/**
 * 系统日志 API
 * 对应后端 app/routers/logs.py（前缀 /api/system/system-logs）
 */

import apiClient from '../http/client'
import type { ApiResponse } from '@/types/common.types'

export interface LogFileInfo {
  name: string
  path: string
  size: number
  size_mb: number
  modified_at: string
  type: string
}

export interface LogContentResponse {
  filename: string
  lines: string[]
  stats: Record<string, unknown>
}

export interface LogStatistics {
  total_files: number
  total_size_mb: number
  error_files: number
  recent_errors: string[]
  log_types: Record<string, number>
}

/** 获取日志文件列表 */
export async function listLogFiles(): Promise<LogFileInfo[]> {
  const res = await apiClient.get<LogFileInfo[]>('/api/system/system-logs/files')
  return res.data
}

/** 读取日志文件内容 */
export async function readLogFile(request: {
  filename: string; lines?: number; level?: string;
  keyword?: string; start_time?: string; end_time?: string
}): Promise<ApiResponse<LogContentResponse>> {
  return apiClient.post<LogContentResponse>('/api/system/system-logs/read', request)
}

/** 导出日志文件 */
export async function exportLogs(request: {
  filenames?: string[]; level?: string;
  start_time?: string; end_time?: string; format?: 'zip' | 'txt'
}): Promise<ApiResponse<unknown>> {
  // POST 请求导出，返回文件下载（由后端决定方式）
  return apiClient.post<unknown>('/api/system/system-logs/export', request)
}

/** 获取日志统计 */
export async function getLogStatistics(days = 7): Promise<ApiResponse<LogStatistics>> {
  return apiClient.get<LogStatistics>('/api/system/system-logs/statistics', { days })
}

/** 删除日志文件 */
export async function deleteLogFile(filename: string): Promise<ApiResponse<Record<string, never>>> {
  return apiClient.delete<Record<string, never>>(`/api/system/system-logs/files/${encodeURIComponent(filename)}`)
}
