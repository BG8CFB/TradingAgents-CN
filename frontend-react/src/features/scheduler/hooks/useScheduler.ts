/**
 * 定时任务管理 Hook
 * 封装任务的 CRUD 操作、执行历史、统计等
 */

import { useState, useCallback, useRef } from 'react'
import { message } from 'antd'
import {
  listSchedulerJobs,
  getJobDetail,
  pauseJob,
  resumeJob,
  triggerJob,
  getJobHistory,
  getAllHistory,
  getSchedulerStats,
  getJobExecutions,
  cancelExecution,
  markExecutionFailed,
  deleteExecution,
  type SchedulerJob,
  type JobExecution,
  type SchedulerStats,
  type JobHistoryResponse,
} from '@/services/api/scheduler'

export interface UseSchedulerReturn {
  jobs: SchedulerJob[]
  stats: SchedulerStats | null
  loading: boolean
  actionLoading: Record<string, boolean>
  fetchJobs: () => Promise<void>
  pause: (jobId: string) => Promise<void>
  resume: (jobId: string) => Promise<void>
  trigger: (jobId: string, force?: boolean) => Promise<void>
  getDetail: (jobId: string) => Promise<SchedulerJob | null>
  loadHistory: (jobId: string, limit?: number, offset?: number) => Promise<JobHistoryResponse>
  loadAllHistory: (params?: { job_id?: string; status?: string; limit?: number; offset?: number }) => Promise<JobHistoryResponse>
  loadExecutions: (params?: {
    job_id?: string; status?: string; is_manual?: boolean | null; limit?: number; offset?: number
  }) => Promise<{ items: JobExecution[]; total: number; limit: number; offset: number }>
  cancelExec: (executionId: string) => Promise<void>
  markFailed: (executionId: string, reason?: string) => Promise<void>
  deleteExec: (executionId: string) => Promise<void>
}

export function useScheduler(): UseSchedulerReturn {
  const [jobs, setJobs] = useState<SchedulerJob[]>([])
  const [stats, setStats] = useState<SchedulerStats | null>(null)
  const [loading, setLoading] = useState(false)
  const [actionLoading, setActionLoading] = useState<Record<string, boolean>>({})

  const fetchingRef = useRef(false)
  const fetchJobs = useCallback(async () => {
    if (fetchingRef.current) return
    fetchingRef.current = true
    setLoading(true)
    try {
      const [jobsRes, statsRes] = await Promise.all([
        listSchedulerJobs(),
        getSchedulerStats(),
      ])
      setJobs(Array.isArray(jobsRes) ? jobsRes : [])
      setStats(statsRes?.data ?? null)
    } catch {
      message.error('加载任务列表失败')
      setJobs([])
      setStats(null)
    } finally {
      setLoading(false)
      fetchingRef.current = false
    }
  }, [])

  const withActionLoading = async <T,>(jobId: string, fn: () => Promise<T>): Promise<T> => {
    setActionLoading(prev => ({ ...prev, [jobId]: true }))
    try {
      return await fn()
    } finally {
      setActionLoading(prev => ({ ...prev, [jobId]: false }))
    }
  }

  const pause = useCallback(async (jobId: string) => {
    await withActionLoading(jobId, async () => {
      await pauseJob(jobId)
      message.success('任务已暂停')
      await fetchJobs()
    })
  }, [fetchJobs])

  const resume = useCallback(async (jobId: string) => {
    await withActionLoading(jobId, async () => {
      await resumeJob(jobId)
      message.success('任务已恢复')
      await fetchJobs()
    })
  }, [fetchJobs])

  const trigger = useCallback(async (jobId: string, force = false) => {
    await withActionLoading(jobId, async () => {
      await triggerJob(jobId, force)
      message.success('任务已触发执行')
      await fetchJobs()
    })
  }, [fetchJobs])

  const getDetail = useCallback(async (jobId: string): Promise<SchedulerJob | null> => {
    try {
      const res = await getJobDetail(jobId)
      return res.data ?? null
    } catch {
      message.error('获取任务详情失败')
      return null
    }
  }, [])

  const loadHistory = useCallback(async (jobId: string, limit = 20, offset = 0) => {
    try {
      const res = await getJobHistory(jobId, limit, offset)
      return res.data ?? { history: [], total: 0, limit, offset }
    } catch {
      message.error('加载执行历史失败')
      return { history: [], total: 0, limit, offset }
    }
  }, [])

  const loadAllHistory = useCallback(async (params?: { job_id?: string; status?: string; limit?: number; offset?: number }) => {
    try {
      const res = await getAllHistory(params?.limit ?? 50, params?.offset ?? 0, params as Record<string, unknown>)
      return res.data ?? { history: [], total: 0, limit: 50, offset: 0 }
    } catch {
      message.error('加载执行历史失败')
      return { history: [], total: 0, limit: 50, offset: 0 }
    }
  }, [])

  const loadExecutions = useCallback(async (params?: { job_id?: string; status?: string; is_manual?: boolean | null; limit?: number; offset?: number }) => {
    try {
      const res = await getJobExecutions(params ?? {})
      return res.data ?? { items: [], total: 0, limit: 20, offset: 0 }
    } catch {
      message.error('加载执行记录失败')
      return { items: [], total: 0, limit: 20, offset: 0 }
    }
  }, [])

  const cancelExec = useCallback(async (executionId: string) => {
    try {
      await cancelExecution(executionId)
      message.success('已设置取消标记')
    } catch {
      message.error('取消失败')
    }
  }, [])

  const markFailed = useCallback(async (executionId: string, reason = '用户手动标记') => {
    try {
      await markExecutionFailed(executionId, reason)
      message.success('已标记为失败')
    } catch {
      message.error('标记失败')
    }
  }, [])

  const deleteExec = useCallback(async (executionId: string) => {
    try {
      await deleteExecution(executionId)
      message.success('执行记录已删除')
    } catch {
      message.error('删除失败')
    }
  }, [])

  return {
    jobs,
    stats,
    loading,
    actionLoading,
    fetchJobs,
    pause,
    resume,
    trigger,
    getDetail,
    loadHistory,
    loadAllHistory,
    loadExecutions,
    cancelExec,
    markFailed,
    deleteExec,
  }
}
