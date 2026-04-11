import { useMemo } from 'react'
import { Input, Tag, Space, Typography } from 'antd'
import { getStockPlaceholder, validateStockSymbol } from '@/services/api/analysis'

const { Text } = Typography

interface BatchStockInputProps {
  values: string[]
  onChange: (values: string[]) => void
  market: string
  disabled?: boolean
  max?: number
}

export default function BatchStockInput({ values, onChange, market, disabled, max = 10 }: BatchStockInputProps) {
  const placeholder = getStockPlaceholder(market)

  const inputValue = useMemo(() => values.join(', '), [values])

  const handleChange = (raw: string) => {
    const parsed = raw
      .split(/[,，\s]+/)
      .map((s) => s.trim().toUpperCase())
      .filter(Boolean)
    onChange(parsed.slice(0, max))
  }

  return (
    <div>
      <Input.TextArea
        value={inputValue}
        onChange={(e) => handleChange(e.target.value)}
        placeholder={placeholder}
        disabled={disabled}
        autoSize={{ minRows: 2, maxRows: 4 }}
      />
      <Space wrap style={{ marginTop: 8 }}>
        {values.map((sym, idx) => {
          const valid = validateStockSymbol(sym, market)
          return (
            <Tag
              key={`${sym}-${idx}`}
              color={valid ? 'processing' : 'error'}
              closable={!disabled}
              onClose={() => onChange(values.filter((_, i) => i !== idx))}
            >
              {sym}
            </Tag>
          )
        })}
      </Space>
      <div style={{ marginTop: 4 }}>
        <Text type="secondary" style={{ fontSize: 12, color: 'var(--text-secondary)' }}>
          支持逗号、空格或换行分隔，最多 {max} 个
        </Text>
      </div>
    </div>
  )
}
