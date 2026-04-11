import { useState, useCallback, useRef, useEffect } from 'react'
import type { AnalysisTask } from '@/types/analysis.types'
import {
  listUserTasks,
  cancelTask as apiCancelTask,
  deleteTask as apiDeleteTask,
  markTaskAsFailed as apiMarkTaskAsFailed,
} from '@/services/api/analysis'

interface UseTaskListOptions {
  pageSize?: number
  initialStatus?: string
  autoRefresh?: boolean
  refreshInterval?: number
}

interface UseTaskListReturn {
  tasks: AnalysisTask[]
  total: number
  loading: boolean
  error: string | null
  hasMore: boolean
  offset: number
  statusFilter: string | undefined
  setStatusFilter: (status: string | undefined) => void
  refresh: () => Promise<void>
  loadMore: () => Promise<void>
  cancelTask: (taskId: string) => Promise<boolean>
  deleteTask: (taskId: string) => Promise<boolean>
  markTaskFailed: (taskId: string) => Promise<boolean>
}

export function useTaskList(options: UseTaskListOptions = {}): UseTaskListReturn {
  const { pageSize = 20, initialStatus, autoRefresh = true, refreshInterval = 10000 } = options

  const [tasks, setTasks] = useState<AnalysisTask[]>([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [offset, setOffset] = useState(0)
  const [statusFilter, setStatusFilter] = useState<string | undefined>(initialStatus)
  const hasMore = offset + pageSize < total

  const isMountedRef = useRef(true)
  const refreshTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  useEffect(() => {
    return () => {
      isMountedRef.current = false
      if (refreshTimerRef.current) {
        clearTimeout(refreshTimerRef.current)
      }
    }
  }, [])

  const clearRefreshTimer = useCallback(() => {
    if (refreshTimerRef.current) {
      clearTimeout(refreshTimerRef.current)
      refreshTimerRef.current = null
    }
  }, [])

  const fetchTasks = useCallback(
    async (targetOffset: number, append = false) => {
      setLoading(true)
      setError(null)
      try {
        const res = await listUserTasks({
          status: statusFilter,
          limit: pageSize,
          offset: targetOffset,
        })
        if (res.success && res.data) {
          const newTasks = res.data.tasks || []
          const newTotal = res.data.total || 0
          if (isMountedRef.current) {
            setTasks((prev) => (append ? [...prev, ...newTasks] : newTasks))
            setTotal(newTotal)
            setOffset(targetOffset + newTasks.length)
          }
        } else {
          if (isMountedRef.current) {
            setError(res.message || '获取任务列表失败')
          }
        }
      } catch (err) {
        if (isMountedRef.current) {
          const msg = err instanceof Error ? err.message : '获取任务列表失败'
          setError(msg)
        }
      } finally {
        if (isMountedRef.current) {
          setLoading(false)
        }
      }
    },
    [pageSize, statusFilter]
  )

  const refresh = useCallback(async () => {
    clearRefreshTimer()
    await fetchTasks(0, false)
  }, [fetchTasks, clearRefreshTimer])

  const loadMore = useCallback(async () => {
    if (loading || !hasMore) return
    await fetchTasks(offset, true)
  }, [fetchTasks, offset, loading, hasMore])

  // auto refresh
  useEffect(() => {
    if (!autoRefresh) return
    refresh()
    const schedule = () => {
      clearRefreshTimer()
      refreshTimerRef.current = setTimeout(() => {
        fetchTasks(0, false).then(() => {
          if (isMountedRef.current) {
            schedule()
          }
        })
      }, refreshInterval)
    }
    schedule()
    return () => clearRefreshTimer()
  }, [autoRefresh, refreshInterval, statusFilter, fetchTasks, refresh, clearRefreshTimer])

  const cancelTask = useCallback(
    async (taskId: string) => {
      try {
        const res = await apiCancelTask(taskId)
        if (res.success) {
          await refresh()
          return true
        }
        return false
      } catch {
        return false
      }
    },
    [refresh]
  )

  const deleteTask = useCallback(
    async (taskId: string) => {
      try {
        const res = await apiDeleteTask(taskId)
        if (res.success) {
          setTasks((prev) => prev.filter((t) => t.task_id !== taskId))
          setTotal((prev) => Math.max(0, prev - 1))
          return true
        }
        return false
      } catch {
        return false
      }
    },
    []
  )

  const markTaskFailed = useCallback(
    async (taskId: string) => {
      try {
        const res = await apiMarkTaskAsFailed(taskId)
        if (res.success) {
          await refresh()
          return true
        }
        return false
      } catch {
        return false
      }
    },
    [refresh]
  )

  return {
    tasks,
    total,
    loading,
    error,
    hasMore,
    offset,
    statusFilter,
    setStatusFilter,
    refresh,
    loadMore,
    cancelTask,
    deleteTask,
    markTaskFailed,
  }
}
