import { useState, useCallback } from 'react'
import type { SingleAnalysisRequest, BatchAnalysisRequest, SingleAnalysisResponse, BatchAnalysisResponse } from '@/types/analysis.types'
import { submitSingleAnalysis, submitBatchAnalysis } from '@/services/api/analysis'

interface UseAnalysisSubmitReturn {
  loading: boolean
  error: string | null
  taskId: string | null
  batchId: string | null
  taskData: SingleAnalysisResponse | null
  batchData: BatchAnalysisResponse | null
  submitSingle: (request: SingleAnalysisRequest) => Promise<boolean>
  submitBatch: (request: BatchAnalysisRequest) => Promise<boolean>
  reset: () => void
}

export function useAnalysisSubmit(): UseAnalysisSubmitReturn {
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [taskId, setTaskId] = useState<string | null>(null)
  const [batchId, setBatchId] = useState<string | null>(null)
  const [taskData, setTaskData] = useState<SingleAnalysisResponse | null>(null)
  const [batchData, setBatchData] = useState<BatchAnalysisResponse | null>(null)

  const submitSingle = useCallback(async (request: SingleAnalysisRequest) => {
    setLoading(true)
    setError(null)
    setTaskId(null)
    setBatchId(null)
    setTaskData(null)
    setBatchData(null)

    try {
      const res = await submitSingleAnalysis(request)
      if (res.success && res.data) {
        setTaskId(res.data.task_id)
        setTaskData(res.data)
        return true
      }
      setError(res.message || '提交单股分析失败')
      return false
    } catch (err) {
      const msg = err instanceof Error ? err.message : '提交单股分析失败'
      setError(msg)
      return false
    } finally {
      setLoading(false)
    }
  }, [])

  const submitBatch = useCallback(async (request: BatchAnalysisRequest) => {
    setLoading(true)
    setError(null)
    setTaskId(null)
    setBatchId(null)
    setTaskData(null)
    setBatchData(null)

    try {
      const res = await submitBatchAnalysis(request)
      if (res.success && res.data) {
        setBatchId(res.data.batch_id)
        setBatchData(res.data)
        return true
      }
      setError(res.message || '提交批量分析失败')
      return false
    } catch (err) {
      const msg = err instanceof Error ? err.message : '提交批量分析失败'
      setError(msg)
      return false
    } finally {
      setLoading(false)
    }
  }, [])

  const reset = useCallback(() => {
    setLoading(false)
    setError(null)
    setTaskId(null)
    setBatchId(null)
    setTaskData(null)
    setBatchData(null)
  }, [])

  return {
    loading,
    error,
    taskId,
    batchId,
    taskData,
    batchData,
    submitSingle,
    submitBatch,
    reset,
  }
}
