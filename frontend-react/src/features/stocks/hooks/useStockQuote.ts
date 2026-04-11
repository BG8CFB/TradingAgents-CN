import { useState, useEffect, useCallback } from 'react'
import { getStockQuote, getStockFundamentals } from '@/services/api/stocks'
import type { StockQuote, StockFundamentals } from '@/types/stocks.types'

interface UseStockQuoteReturn {
  quote: StockQuote | null
  fundamentals: StockFundamentals | null
  loading: boolean
  error: string | null
  refresh: () => void
}

export function useStockQuote(code: string, forceRefresh = false): UseStockQuoteReturn {
  const [quote, setQuote] = useState<StockQuote | null>(null)
  const [fundamentals, setFundamentals] = useState<StockFundamentals | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const fetchData = useCallback(async () => {
    if (!code) return
    setLoading(true)
    setError(null)
    try {
      const [quoteRes, fundamentalsRes] = await Promise.all([
        getStockQuote(code, forceRefresh),
        getStockFundamentals(code, undefined, forceRefresh),
      ])
      if (quoteRes.success && quoteRes.data) {
        setQuote(quoteRes.data)
      }
      if (fundamentalsRes.success && fundamentalsRes.data) {
        setFundamentals(fundamentalsRes.data)
      }
      if (!quoteRes.success && quoteRes.message) {
        setError(quoteRes.message)
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : '获取股票数据失败')
    } finally {
      setLoading(false)
    }
  }, [code, forceRefresh])

  useEffect(() => {
    fetchData()
  }, [fetchData])

  return { quote, fundamentals, loading, error, refresh: fetchData }
}
