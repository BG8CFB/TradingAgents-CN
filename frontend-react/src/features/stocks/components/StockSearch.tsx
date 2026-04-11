import { useState, useRef, useCallback } from 'react'
import { Input, Dropdown, List, Empty, Spin } from 'antd'
import { SearchOutlined } from '@ant-design/icons'
import { searchStocks } from '@/services/api/stocks'
import type { SearchStockResult } from '@/types/stocks.types'

interface StockSearchProps {
  value?: string
  onChange?: (value: string) => void
  onSelect?: (stock: SearchStockResult) => void
  placeholder?: string
  size?: 'small' | 'middle' | 'large'
  style?: React.CSSProperties
}

export default function StockSearch({
  value = '',
  onChange,
  onSelect,
  placeholder = '搜索股票代码或名称',
  size = 'middle',
  style,
}: StockSearchProps) {
  const [query, setQuery] = useState(value)
  const [results, setResults] = useState<SearchStockResult[]>([])
  const [loading, setLoading] = useState(false)
  const [open, setOpen] = useState(false)
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const doSearch = useCallback(async (q: string) => {
    if (!q.trim()) {
      setResults([])
      return
    }
    setLoading(true)
    try {
      const res = await searchStocks(q.trim(), 10)
      if (res.success && res.data) {
        setResults(res.data.data || [])
      }
    } finally {
      setLoading(false)
    }
  }, [])

  const handleChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const v = e.target.value
    setQuery(v)
    onChange?.(v)
    if (timerRef.current) clearTimeout(timerRef.current)
    timerRef.current = setTimeout(() => {
      doSearch(v)
      setOpen(true)
    }, 300)
  }

  const handleSelect = (item: SearchStockResult) => {
    setQuery(`${item.name} (${item.symbol})`)
    setOpen(false)
    onSelect?.(item)
  }

  const dropdownContent = (
    <div
      style={{
        width: 320,
        maxHeight: 320,
        overflow: 'auto',
        background: 'var(--bg-card)',
        borderRadius: 8,
        border: '1px solid rgba(255,255,255,0.08)',
      }}
    >
      {loading ? (
        <div style={{ padding: 24, textAlign: 'center' }}>
          <Spin size="small" />
        </div>
      ) : results.length > 0 ? (
        <List
          size="small"
          dataSource={results}
          renderItem={(item) => (
            <List.Item
              style={{
                padding: '8px 12px',
                cursor: 'pointer',
                borderBottom: '1px solid rgba(255,255,255,0.04)',
              }}
              onClick={() => handleSelect(item)}
            >
              <div style={{ color: 'var(--text-primary)', fontWeight: 500 }}>
                {item.name}
              </div>
              <div style={{ color: 'var(--text-secondary)', fontSize: 12 }}>
                {item.symbol} · {item.market}
              </div>
            </List.Item>
          )}
        />
      ) : query.trim() ? (
        <div style={{ padding: 16 }}>
          <Empty description="未找到股票" image={Empty.PRESENTED_IMAGE_SIMPLE} />
        </div>
      ) : null}
    </div>
  )

  return (
    <Dropdown open={open} dropdownRender={() => dropdownContent} onOpenChange={setOpen}>
      <Input
        size={size}
        prefix={<SearchOutlined style={{ color: 'var(--text-secondary)' }} />}
        placeholder={placeholder}
        value={query}
        onChange={handleChange}
        onFocus={() => query.trim() && setOpen(true)}
        style={{ background: 'var(--bg-base)', borderColor: 'rgba(255,255,255,0.08)', ...style }}
      />
    </Dropdown>
  )
}
