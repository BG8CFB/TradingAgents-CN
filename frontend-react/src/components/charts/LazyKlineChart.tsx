import { lazy, Suspense } from 'react'
import { Spin } from 'antd'
import type { KlineDataItem } from './KlineECharts'

/** K 线图懒加载版本 - 延迟加载 ECharts 减少首屏包体积 */
const KlineECharts = lazy(() =>
  import('./KlineECharts').then((m) => ({ default: m.default }))
)

export default function LazyKlineChart(props: {
  data: KlineDataItem[]
  loading?: boolean
  height?: number | string
  showVolume?: boolean
  maPeriods?: number[]
}) {
  return (
    <Suspense
      fallback={
        <div style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          height: props.height ?? 400,
          background: 'var(--bg-card)',
          borderRadius: 12,
        }}>
          <Spin description="图表加载中..." />
        </div>
      }
    >
      <KlineECharts {...props} />
    </Suspense>
  )
}
