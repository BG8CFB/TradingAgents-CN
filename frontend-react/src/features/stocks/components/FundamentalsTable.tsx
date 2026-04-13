import { Card, Descriptions, Tag, Empty } from 'antd'
import type { StockFundamentals } from '@/types/stocks.types'

interface FundamentalsTableProps {
  data?: StockFundamentals | null
  loading?: boolean
}

export default function FundamentalsTable({ data, loading }: FundamentalsTableProps) {
  if (loading) {
    return (
      <Card style={{ background: 'var(--bg-card)', border: 'none' }}>
        <div style={{ height: 160, display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--text-secondary)' }}>
          加载基本面数据中...
        </div>
      </Card>
    )
  }

  if (!data) {
    return (
      <Card style={{ background: 'var(--bg-card)', border: 'none' }}>
        <Empty description="暂无基本面数据" image={Empty.PRESENTED_IMAGE_SIMPLE} />
      </Card>
    )
  }

  const items = [
    { label: '行业', children: data.industry ? <Tag color="default">{data.industry}</Tag> : '-' },
    { label: '市场', children: data.market || '-' },
    { label: '市盈率 (PE)', children: formatNumber(data.pe) },
    { label: '市净率 (PB)', children: formatNumber(data.pb) },
    { label: 'PE (TTM)', children: formatNumber(data.pe_ttm) },
    { label: 'PB (MRQ)', children: formatNumber(data.pb_mrq) },
    { label: '市销率 (PS)', children: formatNumber(data.ps) },
    { label: '净资产收益率 (ROE)', children: data.roe !== undefined ? `${data.roe}%` : '-' },
    { label: '负债率', children: data.debt_ratio !== undefined ? `${data.debt_ratio}%` : '-' },
    { label: '总市值', children: formatMv(data.total_mv) },
    { label: '流通市值', children: formatMv(data.circ_mv) },
    { label: '数据来源', children: data.pe_is_realtime ? <Tag color="success">实时计算</Tag> : <Tag>静态数据</Tag> },
  ]

  return (
    <Card
      title={<span style={{ color: 'var(--text-primary)' }}>基本面数据</span>}
      style={{ background: 'var(--bg-card)', border: 'none' }}
      styles={{ header: { borderBottom: '1px solid rgba(255,255,255,0.06)' } }}
    >
      <Descriptions
        column={{ xs: 1, sm: 2, md: 3 }}
        items={items}
        styles={{ label: { color: 'var(--text-secondary)' }, content: { color: 'var(--text-primary)' } }}
      />
    </Card>
  )
}

function formatNumber(n: number | undefined | null): string {
  if (n === undefined || n === null) return '-'
  return n.toFixed(2)
}

function formatMv(n: number | undefined | null): string {
  if (n === undefined || n === null) return '-'
  if (n >= 1e8) return (n / 1e8).toFixed(2) + '亿'
  if (n >= 1e4) return (n / 1e4).toFixed(2) + '万'
  return n.toLocaleString()
}
