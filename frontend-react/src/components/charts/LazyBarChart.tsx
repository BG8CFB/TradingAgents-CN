import { lazy, Suspense } from 'react'
import { Spin } from 'antd'

const BarChart = lazy(() =>
  import('./BarChart').then((m) => ({ default: m.default }))
)

export default function LazyBarChart(props: Parameters<typeof BarChart>[0]) {
  return (
    <Suspense
      fallback={
        <div style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          height: props.height ?? 280,
          background: 'var(--bg-card)',
          borderRadius: 12,
        }}>
          <Spin description="图表加载中..." />
        </div>
      }
    >
      <BarChart {...props} />
    </Suspense>
  )
}
