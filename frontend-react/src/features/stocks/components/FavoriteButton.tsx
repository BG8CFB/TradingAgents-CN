import { useState, useEffect, useCallback } from 'react'
import { Button, message } from 'antd'
import { HeartOutlined, HeartFilled } from '@ant-design/icons'
import { checkFavorite, addFavorite, removeFavorite } from '@/services/api/favorites'

interface FavoriteButtonProps {
  stockCode: string
  stockName?: string
  market?: string
  size?: 'small' | 'middle' | 'large'
}

export default function FavoriteButton({ stockCode, stockName, market = 'A股', size = 'middle' }: FavoriteButtonProps) {
  const [isFavorite, setIsFavorite] = useState(false)
  const [loading, setLoading] = useState(false)
  const [checked, setChecked] = useState(false)

  useEffect(() => {
    if (!stockCode) return
    checkFavorite(stockCode)
      .then((res) => {
        if (res.success && res.data) {
          setIsFavorite(res.data.is_favorite)
        }
      })
      .finally(() => setChecked(true))
  }, [stockCode])

  const toggle = useCallback(async () => {
    if (!stockCode) return
    setLoading(true)
    try {
      if (isFavorite) {
        const res = await removeFavorite(stockCode)
        if (res.success) {
          setIsFavorite(false)
          message.success('已取消自选')
        } else {
          message.error(res.message || '取消自选失败')
        }
      } else {
        const res = await addFavorite({
          stock_code: stockCode,
          stock_name: stockName || stockCode,
          market,
        })
        if (res.success) {
          setIsFavorite(true)
          message.success('已添加自选')
        } else {
          message.error(res.message || '添加自选失败')
        }
      }
    } catch (err) {
      message.error(err instanceof Error ? err.message : '操作失败')
    } finally {
      setLoading(false)
    }
  }, [isFavorite, stockCode, stockName, market])

  if (!checked) {
    return (
      <Button size={size} loading disabled>
        自选
      </Button>
    )
  }

  return (
    <Button
      size={size}
      type={isFavorite ? 'primary' : 'default'}
      icon={isFavorite ? <HeartFilled /> : <HeartOutlined />}
      loading={loading}
      onClick={toggle}
      style={
        isFavorite
          ? { background: 'var(--accent-primary)', borderColor: 'var(--accent-primary)' }
          : undefined
      }
    >
      {isFavorite ? '已自选' : '加自选'}
    </Button>
  )
}
