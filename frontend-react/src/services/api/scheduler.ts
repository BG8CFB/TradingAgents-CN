/**
 * 定时任务管理 API
 * 对应后端 app/routers/scheduler.py（前缀 /api/scheduler）
 */

import apiClient from '../http/client'
import type { ApiResponse } from '@/types/common.types'

export interface SchedulerJob {
  id: string
  name: string
  display_name?: string
  description?: string
  enabled: boolean
  next_run_time?: string
  trigger: {
    type: string
    cron_expression?: string
  }
}

export interface JobExecution {
  id: string
  job_id: string
  status: 'success' | 'failed' | 'missed' | 'running'
  started_at: string
  finished_at?: string
  duration_ms?: number
  is_manual: boolean
  result?: string
  error?: string
}

export interface SchedulerStats {
  total_jobs: number
  active_jobs: number
  paused_jobs: number
  today_executions: number
  success_rate: number
}

export interface JobHistoryResponse {
  history: JobExecution[]
  total: number
  limit: number
  offset: number
}

/** 获取所有定时任务 */
export async function listSchedulerJobs(): Promise<ApiResponse<SchedulerJob[]>> {
  return apiClient.get<SchedulerJob[]>('/api/scheduler/jobs')
}

/** 获取任务详情 */
export async function getJobDetail(jobId: string): Promise<ApiResponse<SchedulerJob>> {
  return apiClient.get<SchedulerJob>(`/api/scheduler/jobs/${jobId}`)
}

/** 暂停任务 */
export async function pauseJob(jobId: string): Promise<ApiResponse<Record<string, never>>> {
  return apiClient.post<Record<string, never>>(`/api/scheduler/jobs/${jobId}/pause`)
}

/** 恢复任务 */
export async function resumeJob(jobId: string): Promise<ApiResponse<Record<string, never>>> {
  return apiClient.post<Record<string, never>>(`/api/scheduler/jobs/${jobId}/resume`)
}

/** 手动触发任务 */
export async function triggerJob(jobId: string, force = false): Promise<ApiResponse<Record<string, never>>> {
  const url = force ? `/api/scheduler/jobs/${jobId}/trigger?force=true` : `/api/scheduler/jobs/${jobId}/trigger`
  return apiClient.post<Record<string, never>>(url)
}

/** 获取任务执行历史 */
export async function getJobHistory(jobId: string, limit = 20, offset = 0): Promise<ApiResponse<JobHistoryResponse>> {
  return apiClient.get<JobHistoryResponse>(`/api/scheduler/jobs/${jobId}/history`, { limit, offset })
}

/** 获取所有执行历史 */
export async function getAllHistory(limit = 50, offset = 0, filters?: { job_id?: string; status?: string }): Promise<ApiResponse<JobHistoryResponse>> {
  return apiClient.get<JobHistoryResponse>('/api/scheduler/history', { limit, offset, ...filters })
}

/** 获取调度器统计 */
export async function getSchedulerStats(): Promise<ApiResponse<SchedulerStats>> {
  return apiClient.get<SchedulerStats>('/api/scheduler/stats')
}

/** 调度器健康检查 */
export async function schedulerHealthCheck(): Promise<ApiResponse<unknown>> {
  return apiClient.get<unknown>('/api/scheduler/health')
}

/** 获取任务执行记录（新版） */
export async function getJobExecutions(params?: {
  job_id?: string; status?: string; is_manual?: boolean | null; limit?: number; offset?: number
}): Promise<ApiResponse<{ items: JobExecution[]; total: number; limit: number; offset: number }>> {
  return apiClient.get<{ items: JobExecution[]; total: number; limit: number; offset: number }>('/api/scheduler/executions', params ?? {})
}

/** 取消执行 */
export async function cancelExecution(executionId: string): Promise<ApiResponse<Record<string, never>>> {
  return apiClient.post<Record<string, never>>(`/api/scheduler/executions/${executionId}/cancel`)
}

/** 标记执行为失败 */
export async function markExecutionFailed(executionId: string, reason = '用户手动标记'): Promise<ApiResponse<Record<string, never>>> {
  const url = `/api/scheduler/executions/${executionId}/mark-failed?reason=${encodeURIComponent(reason)}`
  return apiClient.post<Record<string, never>>(url)
}

/** 删除执行记录 */
export async function deleteExecution(executionId: string): Promise<ApiResponse<Record<string, never>>> {
  return apiClient.delete<Record<string, never>>(`/api/scheduler/executions/${executionId}`)
}
