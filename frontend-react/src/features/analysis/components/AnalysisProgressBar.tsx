import { Progress } from 'antd'

interface AnalysisProgressBarProps {
  progress: number
  status?: 'normal' | 'active' | 'success' | 'exception'
  size?: 'small' | 'default'
  showInfo?: boolean
}

export default function AnalysisProgressBar({
  progress,
  status = 'active',
  size = 'default',
  showInfo = true,
}: AnalysisProgressBarProps) {
  const percent = Math.min(Math.max(progress, 0), 100)

  return (
    <Progress
      percent={percent}
      status={status}
      size={size}
      showInfo={showInfo}
      strokeColor={{
        '0%': 'var(--accent-primary)',
        '100%': 'var(--accent-secondary)',
      }}
      trailColor="rgba(255,255,255,0.08)"
      style={{ marginBottom: 0 }}
    />
  )
}
