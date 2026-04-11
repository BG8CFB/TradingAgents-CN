import { useState, useEffect, useCallback } from 'react'
import type { AgentMode } from '@/services/api/agent-configs'
import { getAgentConfig } from '@/services/api/agent-configs'

interface UseAnalystsReturn {
  analysts: AgentMode[]
  loading: boolean
  error: string | null
  refresh: () => Promise<void>
}

export function useAnalysts(): UseAnalystsReturn {
  const [analysts, setAnalysts] = useState<AgentMode[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const refresh = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const res = await getAgentConfig(1)
      if (res.success && res.data) {
        setAnalysts(res.data.customModes || [])
      } else {
        setAnalysts([])
        setError(res.message || '获取分析师列表失败')
      }
    } catch (err) {
      setAnalysts([])
      const msg = err instanceof Error ? err.message : '获取分析师列表失败'
      setError(msg)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    refresh()
  }, [refresh])

  return {
    analysts,
    loading,
    error,
    refresh,
  }
}
