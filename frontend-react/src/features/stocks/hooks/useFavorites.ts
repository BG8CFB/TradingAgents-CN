import { useState, useEffect, useCallback } from 'react'
import { getFavorites, removeFavorite, syncFavoritesRealtime } from '@/services/api/favorites'
import type { FavoriteStock } from '@/types/favorites.types'

interface UseFavoritesReturn {
  favorites: FavoriteStock[]
  loading: boolean
  error: string | null
  refresh: () => void
  remove: (stockCode: string) => Promise<boolean>
  syncRealtime: () => Promise<boolean>
}

export function useFavorites(): UseFavoritesReturn {
  const [favorites, setFavorites] = useState<FavoriteStock[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const fetchData = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const res = await getFavorites()
      if (res.success && res.data) {
        setFavorites(res.data)
      } else {
        setError(res.message || '获取自选股失败')
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : '获取自选股失败')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    fetchData()
  }, [fetchData])

  const remove = useCallback(async (stockCode: string) => {
    const res = await removeFavorite(stockCode)
    if (res.success) {
      setFavorites((prev) => prev.filter((f) => f.stock_code !== stockCode))
      return true
    }
    return false
  }, [])

  const syncRealtime = useCallback(async () => {
    const res = await syncFavoritesRealtime({ data_source: 'tushare' })
    if (res.success) {
      await fetchData()
      return true
    }
    return false
  }, [fetchData])

  return { favorites, loading, error, refresh: fetchData, remove, syncRealtime }
}
