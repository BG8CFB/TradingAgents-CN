import { Checkbox, Spin, Empty, Tag, Space } from 'antd'
import { useAnalysts } from '../hooks/useAnalysts'

interface AnalystTeamSelectorProps {
  value: string[]
  onChange: (value: string[]) => void
  disabled?: boolean
}

export default function AnalystTeamSelector({ value, onChange, disabled }: AnalystTeamSelectorProps) {
  const { analysts, loading, error } = useAnalysts()

  if (loading) {
    return <Spin size="small" />
  }

  if (error || analysts.length === 0) {
    return <Empty description="暂无分析师配置" image={Empty.PRESENTED_IMAGE_SIMPLE} />
  }

  return (
    <Checkbox.Group value={value} onChange={(v) => onChange(v as string[])} disabled={disabled}>
      <Space vertical size="small">
        {analysts.map((analyst) => (
          <Checkbox key={analyst.slug} value={analyst.slug}>
            <Space>
              <span style={{ color: 'var(--text-primary)' }}>{analyst.name}</span>
              {analyst.description && (
                <Tag color="default" style={{ fontSize: 11 }}>
                  {analyst.description}
                </Tag>
              )}
            </Space>
          </Checkbox>
        ))}
      </Space>
    </Checkbox.Group>
  )
}
