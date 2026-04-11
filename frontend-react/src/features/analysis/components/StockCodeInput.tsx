import { Input, Space, Typography } from 'antd'
import { getStockPlaceholder, getStockExamples } from '@/services/api/analysis'

const { Text } = Typography

interface StockCodeInputProps {
  value: string
  onChange: (value: string) => void
  market: string
  disabled?: boolean
  error?: string
}

export default function StockCodeInput({ value, onChange, market, disabled, error }: StockCodeInputProps) {
  const examples = getStockExamples(market)
  const placeholder = getStockPlaceholder(market)

  return (
    <div>
      <Input
        value={value}
        onChange={(e) => onChange(e.target.value.toUpperCase())}
        placeholder={placeholder}
        disabled={disabled}
        status={error ? 'error' : undefined}
        style={{ textTransform: 'uppercase' }}
      />
      {examples.length > 0 && (
        <Space size="small" wrap style={{ marginTop: 8 }}>
          <Text type="secondary" style={{ fontSize: 12, color: 'var(--text-secondary)' }}>
            示例:
          </Text>
          {examples.slice(0, 5).map((ex) => (
            <Text
              key={ex}
              style={{
                fontSize: 12,
                color: 'var(--accent-secondary)',
                cursor: disabled ? 'not-allowed' : 'pointer',
              }}
              onClick={() => !disabled && onChange(ex)}
            >
              {ex}
            </Text>
          ))}
        </Space>
      )}
      {error && (
        <div style={{ color: 'var(--accent-error)', fontSize: 12, marginTop: 4 }}>{error}</div>
      )}
    </div>
  )
}
