import { Table, Empty, Tag } from 'antd'
import type { ScreeningFieldConfig, ScreeningResponse } from '@/types/screening.types'

interface ScreeningResultTableProps {
  data: ScreeningResponse | null
  loading: boolean
  fields: ScreeningFieldConfig | null
}

export default function ScreeningResultTable({ data, loading, fields }: ScreeningResultTableProps) {
  const items = data?.items || []

  if (!loading && items.length === 0) {
    return (
      <div style={{ padding: '48px 0', background: 'var(--bg-card)', borderRadius: 12 }}>
        <Empty description="暂无筛选结果" image={Empty.PRESENTED_IMAGE_SIMPLE} />
      </div>
    )
  }

  // Build columns from first item keys if fields config not available
  const sample = items[0] || {}
  const keys = Object.keys(sample)

  const columns = keys.map((key) => {
    const fieldMeta = fields?.fields?.[key]
    const title = fieldMeta?.label || key

    return {
      title,
      dataIndex: key,
      key,
      ellipsis: true,
      render: (val: unknown) => {
        if (val === null || val === undefined) return '-'
        if (key === 'industry' || key === 'name') {
          return <span style={{ color: 'var(--text-primary)' }}>{String(val)}</span>
        }
        if (typeof val === 'number') {
          const fractionDigits = fieldMeta?.type === 'percent' ? 2 : 2
          return <span style={{ color: 'var(--text-primary)', fontFamily: 'Inter, monospace' }}>{val.toFixed(fractionDigits)}</span>
        }
        if (typeof val === 'boolean') {
          return val ? <Tag color="success">是</Tag> : <Tag>否</Tag>
        }
        return <span style={{ color: 'var(--text-primary)' }}>{String(val)}</span>
      },
    }
  })

  return (
    <Table
      rowKey={(record) => {
        const r = record as Record<string, unknown>
        return String(r.stock_code || r.code || r.symbol || JSON.stringify(record))
      }}
      dataSource={items as Record<string, unknown>[]}
      columns={columns}
      loading={loading}
      pagination={false}
      scroll={{ x: 'max-content' }}
      style={{ background: 'var(--bg-card)', borderRadius: 12 }}
      locale={{
        emptyText: <Empty description="暂无筛选结果" image={Empty.PRESENTED_IMAGE_SIMPLE} />,
      }}
    />
  )
}
