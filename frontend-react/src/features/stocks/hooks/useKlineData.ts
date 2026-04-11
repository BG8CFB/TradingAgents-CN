import { useState, useEffect, useCallback } from 'react'
import { getStockKline } from '@/services/api/stocks'
import type { KlineItem } from '@/types/stocks.types'
import type { KlineDataItem } from '@/components/charts/KlineECharts'

interface UseKlineDataReturn {
  data: KlineDataItem[]
  rawData: KlineItem[]
  loading: boolean
  error: string | null
  refresh: () => void
}

export function useKlineData(code: string, period = 'day', limit = 120): UseKlineDataReturn {
  const [rawData, setRawData] = useState<KlineItem[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const fetchData = useCallback(async () => {
    if (!code) return
    setLoading(true)
    setError(null)
    try {
      const res = await getStockKline(code, period, limit)
      if (res.success && res.data) {
        setRawData(res.data.items || [])
      } else if (res.message) {
        setError(res.message)
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : '获取K线数据失败')
    } finally {
      setLoading(false)
    }
  }, [code, period, limit])

  useEffect(() => {
    fetchData()
  }, [fetchData])

  const chartData: KlineDataItem[] = rawData.map((item) => ({
    date: item.time,
    open: item.open,
    close: item.close,
    low: item.low,
    high: item.high,
    volume: item.volume,
  }))

  return { data: chartData, rawData, loading, error, refresh: fetchData }
}
