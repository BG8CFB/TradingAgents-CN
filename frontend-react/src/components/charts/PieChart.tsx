import { useMemo } from 'react'
import ReactECharts from 'echarts-for-react'
import type { EChartsOption } from 'echarts'

interface PieDataItem {
  name: string
  value: number
}

interface PieChartProps {
  data: PieDataItem[]
  title?: string
  height?: number | string
  showLegend?: boolean
}

export default function PieChart({ data, title, height = 280, showLegend = true }: PieChartProps) {
  const option: EChartsOption = useMemo(
    () => ({
      title: title ? { text: title, left: 'center', textStyle: { fontSize: 14, color: 'var(--text-primary)' } } : undefined,
      tooltip: { trigger: 'item', formatter: '{b}: {c} ({d}%)' },
      legend: showLegend ? { bottom: 0, textStyle: { color: 'var(--text-secondary)', fontSize: 12 } } : undefined,
      color: ['#C9A96E', '#4A7DB8', '#52C41A', '#FF4D4F', '#D48806', '#722ED1', '#13C2C2', '#EB2F96'],
      series: [
        {
          type: 'pie',
          radius: ['40%', '65%'],
          center: ['50%', '45%'],
          avoidLabelOverlap: true,
          itemStyle: { borderRadius: 4, borderColor: 'var(--bg-card)', borderWidth: 2 },
          label: { show: false },
          emphasis: { label: { show: true, fontSize: 13, fontWeight: 'bold' } },
          data,
        },
      ],
    }),
    [data, title, showLegend]
  )

  return <ReactECharts option={option} style={{ width: '100%', height }} notMerge lazyUpdate />
}
