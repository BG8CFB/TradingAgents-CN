import { Tag } from 'antd'
import type { AnalysisStatus, BatchStatus } from '@/types/analysis.types'
import { ANALYSIS_STATUS_LABELS, BATCH_STATUS_LABELS } from '@/services/api/analysis'

interface TaskStatusBadgeProps {
  status: AnalysisStatus | BatchStatus | string
}

const statusColorMap: Record<string, string> = {
  pending: 'default',
  processing: 'processing',
  running: 'processing',
  completed: 'success',
  partial_success: 'warning',
  failed: 'error',
  cancelled: 'default',
}

export default function TaskStatusBadge({ status }: TaskStatusBadgeProps) {
  const color = statusColorMap[status] || 'default'
  const label = ANALYSIS_STATUS_LABELS[status] || BATCH_STATUS_LABELS[status] || status

  return (
    <Tag color={color} style={{ fontWeight: 500 }}>
      {label}
    </Tag>
  )
}
