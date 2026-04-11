import { Timeline, Typography } from 'antd'
import {
  CheckCircleOutlined,
  LoadingOutlined,
  CloseCircleOutlined,
  ClockCircleOutlined,
} from '@ant-design/icons'
import type { AnalysisStep } from '@/types/analysis.types'

const { Text } = Typography

interface AnalysisStepTimelineProps {
  steps?: AnalysisStep[]
  currentStepName?: string
}

export default function AnalysisStepTimeline({ steps = [], currentStepName }: AnalysisStepTimelineProps) {
  if (steps.length === 0) {
    return (
      <div style={{ color: 'var(--text-secondary)', padding: '16px 0' }}>
        暂无步骤信息
      </div>
    )
  }

  const items = steps.map((step) => {
    let dot: React.ReactNode = <ClockCircleOutlined />
    let color = 'gray'

    switch (step.status) {
      case 'success':
        dot = <CheckCircleOutlined />
        color = 'green'
        break
      case 'active':
        dot = <LoadingOutlined />
        color = 'var(--accent-primary)'
        break
      case 'error':
        dot = <CloseCircleOutlined />
        color = 'red'
        break
      default:
        dot = <ClockCircleOutlined />
        color = 'gray'
    }

    const isCurrent = step.name === currentStepName || step.status === 'active'

    return {
      children: (
        <div>
          <Text strong style={{ color: isCurrent ? 'var(--accent-primary)' : 'var(--text-primary)' }}>
            {step.title || step.name}
          </Text>
          <div style={{ fontSize: 12, color: 'var(--text-secondary)', marginTop: 4 }}>
            {step.description}
          </div>
          {step.error_message && (
            <div style={{ fontSize: 12, color: 'var(--accent-error)', marginTop: 4 }}>
              {step.error_message}
            </div>
          )}
        </div>
      ),
      dot,
      color,
    }
  })

  return <Timeline items={items} style={{ marginTop: 16 }} />
}
