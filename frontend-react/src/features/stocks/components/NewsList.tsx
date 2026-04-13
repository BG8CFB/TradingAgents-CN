import { useState, useEffect, useCallback } from 'react'
import { Card, Typography, Tag, Empty, Button } from 'antd'
import { getStockNews } from '@/services/api/stocks'
import type { NewsItem } from '@/types/stocks.types'

const { Text, Link } = Typography

interface NewsListProps {
  code: string
  limit?: number
}

export default function NewsList({ code, limit = 20 }: NewsListProps) {
  const [news, setNews] = useState<NewsItem[]>([])
  const [loading, setLoading] = useState(false)

  const fetchNews = useCallback(async () => {
    if (!code) return
    setLoading(true)
    try {
      const res = await getStockNews(code, 30, limit)
      if (res.success && res.data) {
        setNews(res.data.items || [])
      }
    } finally {
      setLoading(false)
    }
  }, [code, limit])

  useEffect(() => {
    fetchNews()
  }, [fetchNews])

  return (
    <Card
      title={<span style={{ color: 'var(--text-primary)' }}>新闻资讯</span>}
      style={{ background: 'var(--bg-card)', border: 'none' }}
      styles={{ header: { borderBottom: '1px solid rgba(255,255,255,0.06)' } }}
      extra={
        <Button type="link" onClick={fetchNews} loading={loading}>
          刷新
        </Button>
      }
    >
      {news.length === 0 ? (
        <Empty description="暂无新闻" image={Empty.PRESENTED_IMAGE_SIMPLE} />
      ) : (
        <div>
          {news.map((item, index) => (
            <div
              key={`${item.title}-${index}`}
              style={{ borderBottom: '1px solid rgba(255,255,255,0.04)', padding: '12px 0' }}
            >
              <div style={{ width: '100%' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
                  <Text strong style={{ color: 'var(--text-primary)', flex: 1, marginRight: 12 }}>
                    {item.url ? (
                      <Link href={item.url} target="_blank" style={{ color: 'var(--accent-secondary)' }}>
                        {item.title}
                      </Link>
                    ) : (
                      item.title
                    )}
                  </Text>
                  {item.source && <Tag color="default" style={{ fontSize: 11 }}>{item.source}</Tag>}
                </div>
                {item.summary && (
                  <div style={{ color: 'var(--text-secondary)', fontSize: 13, marginTop: 4 }}>
                    {item.summary}
                  </div>
                )}
                {item.time && (
                  <div style={{ color: 'var(--text-secondary)', fontSize: 12, marginTop: 4 }}>
                    {new Date(item.time).toLocaleString()}
                  </div>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </Card>
  )
}
