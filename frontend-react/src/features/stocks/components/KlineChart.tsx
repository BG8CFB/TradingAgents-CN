import { useState } from 'react'
import { Card, Segmented, Space } from 'antd'
import KlineECharts from '@/components/charts/KlineECharts'
import { useKlineData } from '../hooks/useKlineData'

const PERIODS = [
  { label: '日线', value: 'day' },
  { label: '周线', value: 'week' },
  { label: '月线', value: 'month' },
]

interface KlineChartProps {
  code: string
  height?: number
}

export default function KlineChart({ code, height = 360 }: KlineChartProps) {
  const [period, setPeriod] = useState('day')
  const { data, loading } = useKlineData(code, period, 120)

  return (
    <Card
      title={
        <Space>
          <span style={{ color: 'var(--text-primary)' }}>K线图</span>
          <Segmented
            size="small"
            options={PERIODS.map((p) => ({ label: p.label, value: p.value }))}
            value={period}
            onChange={(v) => setPeriod(v as string)}
            style={{ background: 'var(--bg-base)' }}
          />
        </Space>
      }
      style={{ background: 'var(--bg-card)', border: 'none' }}
      styles={{ header: { borderBottom: '1px solid rgba(255,255,255,0.06)' } }}
    >
      <KlineECharts data={data} loading={loading} height={height} showVolume />
    </Card>
  )
}
