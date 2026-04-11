import { useMemo } from 'react'
import ReactECharts from 'echarts-for-react'
import type { EChartsOption } from 'echarts'

export interface KlineDataItem {
  date: string
  open: number
  close: number
  low: number
  high: number
  volume?: number
}

interface KlineEChartsProps {
  data: KlineDataItem[]
  loading?: boolean
  height?: number | string
  showVolume?: boolean
  maPeriods?: number[]
}

const UP_COLOR = 'var(--accent-success)'
const DOWN_COLOR = 'var(--accent-error)'
const BG_COLOR = 'transparent'
const TEXT_COLOR = 'var(--text-secondary)'
const GRID_COLOR = 'rgba(255,255,255,0.06)'

export default function KlineECharts({
  data,
  loading,
  height = 400,
  showVolume = true,
  maPeriods = [5, 10, 20, 30],
}: KlineEChartsProps) {
  const categories = useMemo(() => data.map((d) => d.date), [data])
  const values = useMemo(() => data.map((d) => [d.open, d.close, d.low, d.high]), [data])
  const volumes = useMemo(() => data.map((d, i) => [i, d.volume ?? 0, d.close > d.open ? 1 : -1]), [data])

  const maSeries = useMemo(() => {
    return maPeriods.map((period) => {
      const result: (number | null)[] = []
      for (let i = 0; i < data.length; i++) {
        if (i < period - 1) {
          result.push(null)
          continue
        }
        let sum = 0
        for (let j = 0; j < period; j++) {
          sum += data[i - j].close
        }
        result.push(Number((sum / period).toFixed(2)))
      }
      return {
        name: `MA${period}`,
        type: 'line' as const,
        data: result,
        smooth: true,
        showSymbol: false,
        lineStyle: { width: 1 },
      }
    })
  }, [data, maPeriods])

  const option: EChartsOption = useMemo(() => {
    const hasVolume = showVolume && data.some((d) => typeof d.volume === 'number')
    const grids = hasVolume
      ? [
          { left: '3%', right: '3%', top: '10%', height: '55%' },
          { left: '3%', right: '3%', top: '70%', height: '16%' },
        ]
      : [{ left: '3%', right: '3%', top: '10%', height: '75%' }]

    const xAxes = hasVolume
      ? [
          { type: 'category' as const, data: categories, scale: true, boundaryGap: false, axisLine: { onZero: false, lineStyle: { color: GRID_COLOR } }, axisLabel: { color: TEXT_COLOR }, splitLine: { show: false }, min: 'dataMin' as const, max: 'dataMax' as const },
          { type: 'category' as const, gridIndex: 1, data: categories, scale: true, boundaryGap: false, axisLine: { onZero: false, lineStyle: { color: GRID_COLOR } }, axisTick: { show: false }, splitLine: { show: false }, axisLabel: { show: false }, min: 'dataMin' as const, max: 'dataMax' as const },
        ]
      : [
          { type: 'category' as const, data: categories, scale: true, boundaryGap: false, axisLine: { onZero: false, lineStyle: { color: GRID_COLOR } }, axisLabel: { color: TEXT_COLOR }, splitLine: { show: false }, min: 'dataMin' as const, max: 'dataMax' as const },
        ]

    const yAxes = hasVolume
      ? [
          { scale: true, splitArea: { show: false }, axisLabel: { color: TEXT_COLOR }, splitLine: { lineStyle: { color: GRID_COLOR } } },
          { scale: true, gridIndex: 1, splitNumber: 2, axisLabel: { show: false }, axisLine: { show: false }, axisTick: { show: false }, splitLine: { show: false } },
        ]
      : [
          { scale: true, splitArea: { show: false }, axisLabel: { color: TEXT_COLOR }, splitLine: { lineStyle: { color: GRID_COLOR } } },
        ]

    const series: EChartsOption['series'] = [
      {
        name: 'K线',
        type: 'candlestick',
        data: values,
        itemStyle: {
          color: UP_COLOR,
          color0: DOWN_COLOR,
          borderColor: UP_COLOR,
          borderColor0: DOWN_COLOR,
        },
        ...(hasVolume ? { xAxisIndex: 0, yAxisIndex: 0 } : {}),
      },
      ...maSeries,
    ]

    if (hasVolume) {
      series.push({
        name: '成交量',
        type: 'bar',
        xAxisIndex: 1,
        yAxisIndex: 1,
        data: volumes,
        itemStyle: {
          color: (params: unknown) => {
            const p = params as { value: [number, number, number] }
            return p.value[2] > 0 ? UP_COLOR : DOWN_COLOR
          },
        },
      })
    }

    return {
      backgroundColor: BG_COLOR,
      animation: false,
      tooltip: {
        trigger: 'axis',
        axisPointer: { type: 'cross' },
        backgroundColor: 'rgba(20,22,39,0.95)',
        borderColor: 'rgba(255,255,255,0.1)',
        textStyle: { color: 'var(--text-primary)' },
      },
      legend: {
        data: ['K线', ...maPeriods.map((p) => `MA${p}`), ...(hasVolume ? ['成交量'] : [])],
        textStyle: { color: TEXT_COLOR },
        top: 0,
      },
      grid: grids,
      xAxis: xAxes,
      yAxis: yAxes,
      dataZoom: [
        { type: 'inside', xAxisIndex: hasVolume ? [0, 1] : [0], start: 50, end: 100 },
        { show: true, xAxisIndex: hasVolume ? [0, 1] : [0], type: 'slider', top: '88%', height: '10%', start: 50, end: 100, textStyle: { color: TEXT_COLOR }, borderColor: GRID_COLOR, fillerColor: 'rgba(201,169,110,0.15)', handleStyle: { color: 'var(--accent-primary)' } },
      ],
      series,
    }
  }, [categories, values, volumes, maPeriods, maSeries, data, showVolume])

  if (loading) {
    return (
      <div
        style={{
          height,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          color: 'var(--text-secondary)',
          background: 'var(--bg-card)',
          borderRadius: 12,
        }}
      >
        加载中...
      </div>
    )
  }

  if (data.length === 0) {
    return (
      <div
        style={{
          height,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          color: 'var(--text-secondary)',
          background: 'var(--bg-card)',
          borderRadius: 12,
        }}
      >
        暂无数据
      </div>
    )
  }

  return (
    <ReactECharts
      option={option}
      style={{ width: '100%', height }}
      notMerge
      lazyUpdate
    />
  )
}
