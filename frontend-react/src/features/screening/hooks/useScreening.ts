import { useState, useEffect, useCallback } from 'react'
import { getScreeningFields, runScreening, getIndustries } from '@/services/api/screening'
import type { ScreeningFieldConfig, ScreeningConditionChild, IndustryItem, ScreeningResponse } from '@/types/screening.types'

interface UseScreeningReturn {
  fields: ScreeningFieldConfig | null
  industries: IndustryItem[]
  loading: boolean
  screening: boolean
  error: string | null
  result: ScreeningResponse | null
  refreshFields: () => void
  run: (conditions: ScreeningConditionChild[], market?: string, limit?: number, offset?: number) => Promise<void>
}

export function useScreening(): UseScreeningReturn {
  const [fields, setFields] = useState<ScreeningFieldConfig | null>(null)
  const [industries, setIndustries] = useState<IndustryItem[]>([])
  const [loading, setLoading] = useState(false)
  const [screening, setScreening] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [result, setResult] = useState<ScreeningResponse | null>(null)

  const fetchFields = useCallback(async () => {
    setLoading(true)
    try {
      const [fieldsRes, industriesRes] = await Promise.all([
        getScreeningFields(),
        getIndustries(),
      ])
      if (fieldsRes.success && fieldsRes.data) {
        setFields(fieldsRes.data)
      }
      if (industriesRes.success && industriesRes.data) {
        setIndustries(industriesRes.data.industries || [])
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : '获取筛选配置失败')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    fetchFields()
  }, [fetchFields])

  const run = useCallback(async (conditions: ScreeningConditionChild[], market = 'CN', limit = 50, offset = 0) => {
    setScreening(true)
    setError(null)
    try {
      const res = await runScreening({
        market,
        conditions: { logic: 'AND', children: conditions },
        limit,
        offset,
      })
      if (res.success && res.data) {
        setResult(res.data)
      } else {
        setError(res.message || '筛选失败')
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : '筛选失败')
    } finally {
      setScreening(false)
    }
  }, [])

  return { fields, industries, loading, screening, error, result, refreshFields: fetchFields, run }
}
