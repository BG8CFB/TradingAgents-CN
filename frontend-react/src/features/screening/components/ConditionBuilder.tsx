import { useState } from 'react'
import { Select, InputNumber, Button, Space, Card, Tag } from 'antd'
import { PlusOutlined } from '@ant-design/icons'
import type { ScreeningConditionChild, ScreeningFieldConfig } from '@/types/screening.types'

interface ConditionBuilderProps {
  fields: ScreeningFieldConfig | null
  industries: { value: string; label: string }[]
  value: ScreeningConditionChild[]
  onChange: (value: ScreeningConditionChild[]) => void
  disabled?: boolean
}

const OPERATORS = [
  { label: '>', value: 'gt' },
  { label: '>=', value: 'gte' },
  { label: '<', value: 'lt' },
  { label: '<=', value: 'lte' },
  { label: '=', value: 'eq' },
  { label: '介于', value: 'between' },
]

export default function ConditionBuilder({ fields, industries, value, onChange, disabled }: ConditionBuilderProps) {
  const [selectedField, setSelectedField] = useState<string>('')
  const [selectedOp, setSelectedOp] = useState<ScreeningConditionChild['op']>('gt')
  const [numValue, setNumValue] = useState<number | null>(null)
  const [numValue2, setNumValue2] = useState<number | null>(null)
  const [selectedIndustry, setSelectedIndustry] = useState<string>('')

  const fieldList = fields?.categories
    ? Object.values(fields.categories).flat()
    : []

  const addCondition = () => {
    if (selectedIndustry) {
      const newCond: ScreeningConditionChild = { field: 'industry', op: 'eq', value: selectedIndustry }
      onChange([...value, newCond])
      setSelectedIndustry('')
      return
    }
    if (!selectedField || numValue === null) return
    const newCond: ScreeningConditionChild =
      selectedOp === 'between' && numValue2 !== null
        ? { field: selectedField, op: 'between', value: [numValue, numValue2] }
        : { field: selectedField, op: selectedOp, value: numValue }
    onChange([...value, newCond])
    setSelectedField('')
    setNumValue(null)
    setNumValue2(null)
  }

  const removeCondition = (idx: number) => {
    onChange(value.filter((_, i) => i !== idx))
  }

  const formatCondition = (cond: ScreeningConditionChild) => {
    if (cond.field === 'industry') return `行业 = ${cond.value}`
    const opLabel = OPERATORS.find((o) => o.value === cond.op)?.label || cond.op
    const valStr = Array.isArray(cond.value) ? `${cond.value[0]} ~ ${cond.value[1]}` : String(cond.value)
    const fieldLabel = fields?.fields?.[cond.field]?.label || cond.field
    return `${fieldLabel} ${opLabel} ${valStr}`
  }

  return (
    <Card style={{ background: 'var(--bg-card)', border: 'none' }}>
      <Space vertical size="middle" style={{ width: '100%' }}>
        <Space wrap>
          <Select
            placeholder="选择字段"
            style={{ width: 140 }}
            value={selectedField || undefined}
            onChange={(v) => { setSelectedField(v); setSelectedIndustry('') }}
            disabled={disabled}
            options={fieldList.map((f) => ({ label: fields?.fields?.[f]?.label || f, value: f }))}
          />
          <Select
            placeholder="操作符"
            style={{ width: 100 }}
            value={selectedOp}
            onChange={setSelectedOp}
            disabled={disabled}
            options={OPERATORS}
          />
          {selectedOp === 'between' ? (
            <>
              <InputNumber
                placeholder="最小值"
                value={numValue}
                onChange={setNumValue}
                disabled={disabled}
                style={{ width: 110 }}
              />
              <span style={{ color: 'var(--text-secondary)' }}>~</span>
              <InputNumber
                placeholder="最大值"
                value={numValue2}
                onChange={setNumValue2}
                disabled={disabled}
                style={{ width: 110 }}
              />
            </>
          ) : (
            <InputNumber
              placeholder="数值"
              value={numValue}
              onChange={setNumValue}
              disabled={disabled}
              style={{ width: 120 }}
            />
          )}
          <span style={{ color: 'var(--text-secondary)' }}>或</span>
          <Select
            placeholder="选择行业"
            style={{ width: 160 }}
            value={selectedIndustry || undefined}
            onChange={(v) => { setSelectedIndustry(v); setSelectedField('') }}
            disabled={disabled}
            options={industries.map((i) => ({ label: i.label, value: i.value }))}
            showSearch
          />
          <Button type="primary" icon={<PlusOutlined />} onClick={addCondition} disabled={disabled}>
            添加
          </Button>
        </Space>

        <Space wrap>
          {value.map((cond, idx) => (
            <Tag
              key={`${cond.field}-${idx}`}
              closable
              onClose={() => removeCondition(idx)}
              style={{ background: 'rgba(201,169,110,0.10)', borderColor: 'rgba(201,169,110,0.25)', color: 'var(--text-primary)' }}
            >
              {formatCondition(cond)}
            </Tag>
          ))}
          {value.length === 0 && (
            <span style={{ color: 'var(--text-secondary)' }}>未添加筛选条件，将返回全部股票</span>
          )}
        </Space>
      </Space>
    </Card>
  )
}
