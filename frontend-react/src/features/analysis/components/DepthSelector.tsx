import { Select } from 'antd'

const depthOptions = [
  { value: 'quick', label: '快速分析 (1-2分钟)', desc: '基础观点' },
  { value: 'basic', label: '基础分析 (3-5分钟)', desc: '常规框架' },
  { value: 'standard', label: '标准分析 (5-8分钟)', desc: '多维度评估' },
  { value: 'deep', label: '深度分析 (10-15分钟)', desc: '全面研判' },
  { value: 'comprehensive', label: '全面分析 (15-30分钟)', desc: '全景报告' },
] as const

interface DepthSelectorProps {
  value?: string
  onChange?: (value: string) => void
  disabled?: boolean
}

export default function DepthSelector({ value, onChange, disabled }: DepthSelectorProps) {
  return (
    <Select
      value={value}
      onChange={onChange}
      disabled={disabled}
      placeholder="请选择分析深度"
      style={{ width: '100%' }}
      options={depthOptions.map((d) => ({ value: d.value, label: d.label }))}
    />
  )
}
