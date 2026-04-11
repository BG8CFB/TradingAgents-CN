import { useState, useEffect, useCallback, useRef } from 'react'
import type { AnalysisResult, TaskStatusData, SSEProgressData } from '@/types/analysis.types'
import { getTaskStatus, getTaskResult, connectTaskSSE } from '@/services/api/analysis'

interface UseAnalysisProgressOptions {
  taskId?: string
  /** 非运行状态时的轮询间隔（毫秒），默认 3000 */
  pollInterval?: number
}

interface UseAnalysisProgressReturn {
  /** 当前进度 0-100 */
  progress: number
  /** 任务状态 */
  status: string
  /** 当前步骤描述 */
  currentStep: string
  /** 步骤详情 */
  stepDetail: string
  /** 分析结果（完成后） */
  result: AnalysisResult | null
  /** 是否还在运行中 */
  isRunning: boolean
  /** 错误信息 */
  error: string | null
  /** SSE 是否已连接 */
  isConnected: boolean
  /** 手动刷新状态 */
  refresh: () => Promise<void>
}

export function useAnalysisProgress(options: UseAnalysisProgressOptions): UseAnalysisProgressReturn {
  const { taskId, pollInterval = 3000 } = options

  const [progress, setProgress] = useState(0)
  const [status, setStatus] = useState<string>('pending')
  const [currentStep, setCurrentStep] = useState('')
  const [stepDetail, setStepDetail] = useState('')
  const [result, setResult] = useState<AnalysisResult | null>(null)
  const [isRunning, setIsRunning] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [isConnected, setIsConnected] = useState(false)

  const pollTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const esRef = useRef<EventSource | null>(null)
  const fetchingResultRef = useRef(false)
  const isRunningRef = useRef(isRunning)

  useEffect(() => {
    isRunningRef.current = isRunning
  }, [isRunning])

  const clearPollTimer = useCallback(() => {
    if (pollTimerRef.current) {
      clearTimeout(pollTimerRef.current)
      pollTimerRef.current = null
    }
  }, [])

  const closeSSE = useCallback(() => {
    if (esRef.current) {
      esRef.current.close()
      esRef.current = null
    }
    setIsConnected(false)
  }, [])

  const fetchStatus = useCallback(async () => {
    if (!taskId) return
    try {
      const res = await getTaskStatus(taskId)
      if (res.success && res.data) {
        applyStatusData(res.data)
      }
    } catch {
      // 轮询时不主动阻断，错误由 SSE 或最终超时处理
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [taskId])

  const fetchResult = useCallback(async () => {
    if (!taskId || fetchingResultRef.current) return
    fetchingResultRef.current = true
    try {
      const res = await getTaskResult(taskId)
      if (res.success && res.data) {
        setResult(res.data)
      }
    } catch {
      // ignore
    } finally {
      fetchingResultRef.current = false
    }
  }, [taskId])

  const applyProgressData = useCallback((data: SSEProgressData) => {
    if (data.progress !== undefined) setProgress(data.progress)
    if (data.status) setStatus(data.status)
    if (data.current_step) setCurrentStep(data.current_step)
    if (data.step_detail) setStepDetail(data.step_detail)

    const runningStates = ['pending', 'processing', 'running', 'queued']
    const finishedStates = ['completed', 'failed', 'cancelled']
    const isDone = finishedStates.includes(data.status || '')
    const isRun = runningStates.includes(data.status || '')
    setIsRunning(isRun && !isDone)

    if (isDone) {
      setIsRunning(false)
      if (data.status === 'completed') {
        fetchResult()
      }
      closeSSE()
      clearPollTimer()
    }
  }, [clearPollTimer, closeSSE, fetchResult])

  const applyStatusData = useCallback((data: TaskStatusData) => {
    setProgress(data.progress ?? 0)
    setStatus(data.status)
    setCurrentStep(data.current_step || '')
    setStepDetail(data.message || '')

    const runningStates = ['pending', 'processing', 'running', 'queued']
    const finishedStates = ['completed', 'failed', 'cancelled']
    const isDone = finishedStates.includes(data.status)
    const isRun = runningStates.includes(data.status)
    setIsRunning(isRun && !isDone)

    if (isDone) {
      setIsRunning(false)
      if (data.status === 'completed') {
        fetchResult()
      }
      closeSSE()
      clearPollTimer()
    }
  }, [clearPollTimer, closeSSE, fetchResult])

  // 建立 SSE 连接
  useEffect(() => {
    if (!taskId) {
      closeSSE()
      clearPollTimer()
      setProgress(0)
      setStatus('pending')
      setCurrentStep('')
      setStepDetail('')
      setResult(null)
      setIsRunning(false)
      setError(null)
      return
    }

    setError(null)

    // 先拉一次状态
    fetchStatus()

    // 建立 SSE
    const es = connectTaskSSE(taskId)
    esRef.current = es

    es.onopen = () => {
      setIsConnected(true)
    }

    es.addEventListener('connected', () => {
      setIsConnected(true)
    })

    es.addEventListener('progress', (event) => {
      try {
        const data = JSON.parse((event as MessageEvent).data) as SSEProgressData
        applyProgressData(data)
      } catch {
        // ignore
      }
    })

    es.addEventListener('heartbeat', () => {
      setIsConnected(true)
    })

    es.addEventListener('error', (event) => {
      try {
        const data = JSON.parse((event as MessageEvent).data) as SSEProgressData
        setError(data.error || '进度流连接异常')
      } catch {
        setError('进度流连接异常')
      }
      setIsConnected(false)
    })

    es.addEventListener('finished', (event) => {
      try {
        const data = JSON.parse((event as MessageEvent).data) as SSEProgressData
        applyProgressData(data)
      } catch {
        // ignore
      }
      closeSSE()
    })

    es.onerror = () => {
      setIsConnected(false)
    }

    // fallback 轮询
    const schedulePoll = () => {
      clearPollTimer()
      pollTimerRef.current = setTimeout(async () => {
        await fetchStatus()
        if (isRunningRef.current) {
          schedulePoll()
        }
      }, pollInterval)
    }
    schedulePoll()

    return () => {
      closeSSE()
      clearPollTimer()
    }
  }, [taskId, pollInterval, fetchStatus, applyProgressData, clearPollTimer, closeSSE])

  const refresh = useCallback(async () => {
    await fetchStatus()
    if (status === 'completed' && !result) {
      await fetchResult()
    }
  }, [fetchStatus, fetchResult, status, result])

  return {
    progress,
    status,
    currentStep,
    stepDetail,
    result,
    isRunning,
    error,
    isConnected,
    refresh,
  }
}
