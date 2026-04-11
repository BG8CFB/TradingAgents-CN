import { useMemo } from 'react'
import ReactECharts from 'echarts-for-react'
import * as echarts from 'echarts'
import type { EChartsOption } from 'echarts'

interface BarDataItem {
  name: string
  value: number
}

interface BarChartProps {
  data: BarDataItem[]
  title?: string
  height?: number | string
  horizontal?: boolean
  showXAxisLabel?: boolean
}

export default function BarChart({
  data,
  title,
  height = 280,
  horizontal = false,
  showXAxisLabel = true,
}: BarChartProps) {
  const option: EChartsOption = useMemo(
    () => ({
      title: title ? { text: title, left: 'center', textStyle: { fontSize: 14, color: 'var(--text-primary)' } } : undefined,
      tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
      grid: { left: horizontal ? '12%' : '3%', right: '3%', bottom: '10%', top: title ? 40 : 20, containLabel: true },
      xAxis: horizontal
        ? undefined
        : { type: 'category', data: data.map((d) => d.name), axisLabel: { show: showXAxisLabel, color: 'var(--text-secondary)', fontSize: 11 }, axisLine: { lineStyle: { color: 'rgba(201,169,110,0.2)' } } },
      yAxis: horizontal
        ? { type: 'category', data: data.map((d) => d.name), axisLabel: { color: 'var(--text-secondary)', fontSize: 11 }, axisLine: { lineStyle: { color: 'rgba(201,169,110,0.2)' } } }
        : { type: 'value', axisLabel: { color: 'var(--text-secondary)' }, splitLine: { lineStyle: { color: 'rgba(201,169,110,0.1)' } } },
      series: [
        {
          type: 'bar',
          data: data.map((d) => d.value),
          barWidth: horizontal ? undefined : '50%',
          itemStyle: {
            borderRadius: horizontal ? [0, 4, 4, 0] : [4, 4, 0, 0],
            color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
              { offset: 0, color: '#C9A96E' },
              { offset: 1, color: '#D4A574' },
            ]),
          },
          emphasis: { itemStyle: { color: '#D4A574' } },
        },
      ],
    }),
    [data, title, horizontal, showXAxisLabel]
  )

  return <ReactECharts option={option} style={{ width: '100%', height }} notMerge lazyUpdate />
}
