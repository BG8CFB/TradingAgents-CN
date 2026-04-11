import { Card, Input, Switch, Slider, Space, Typography, Divider, Row, Col } from 'antd'
import { AnalysisPhases } from '@/constants/analysts'
import AnalystTeamSelector from './AnalystTeamSelector'
import DepthSelector from './DepthSelector'

const { Text } = Typography

export interface AnalysisConfigFormValues {
  selected_analysts?: string[]
  research_depth?: string
  custom_prompt?: string
  include_sentiment?: boolean
  include_risk?: boolean
  phase2_enabled?: boolean
  phase2_debate_rounds?: number
  phase3_enabled?: boolean
  phase3_debate_rounds?: number
  phase4_enabled?: boolean
  phase4_debate_rounds?: number
  mcp_enabled?: boolean
}

interface AnalysisConfigFormProps {
  values: AnalysisConfigFormValues
  onChange: (values: AnalysisConfigFormValues) => void
  disabled?: boolean
}

export default function AnalysisConfigForm({ values, onChange, disabled }: AnalysisConfigFormProps) {
  const update = (patch: Partial<AnalysisConfigFormValues>) => {
    onChange({ ...values, ...patch })
  }

  return (
    <Space vertical size="middle" style={{ width: '100%' }}>
      <Card
        title={<span style={{ color: 'var(--text-primary)' }}>分析深度</span>}
        style={{ background: 'var(--bg-card)', border: 'none' }}
        styles={{ header: { borderBottom: '1px solid rgba(255,255,255,0.06)' } }}
      >
        <DepthSelector
          value={values.research_depth}
          onChange={(v) => update({ research_depth: v })}
          disabled={disabled}
        />
      </Card>

      <Card
        title={<span style={{ color: 'var(--text-primary)' }}>分析师团队</span>}
        style={{ background: 'var(--bg-card)', border: 'none' }}
        styles={{ header: { borderBottom: '1px solid rgba(255,255,255,0.06)' } }}
      >
        <AnalystTeamSelector
          value={values.selected_analysts || []}
          onChange={(v) => update({ selected_analysts: v })}
          disabled={disabled}
        />
      </Card>

      <Card
        title={<span style={{ color: 'var(--text-primary)' }}>高级选项</span>}
        style={{ background: 'var(--bg-card)', border: 'none' }}
        styles={{ header: { borderBottom: '1px solid rgba(255,255,255,0.06)' } }}
      >
        <Space vertical size="middle" style={{ width: '100%' }}>
          <Row align="middle">
            <Col span={12}>
              <Text style={{ color: 'var(--text-primary)' }}>包含情绪分析</Text>
            </Col>
            <Col span={12} style={{ textAlign: 'right' }}>
              <Switch
                checked={values.include_sentiment !== false}
                onChange={(v) => update({ include_sentiment: v })}
                disabled={disabled}
              />
            </Col>
          </Row>

          <Row align="middle">
            <Col span={12}>
              <Text style={{ color: 'var(--text-primary)' }}>包含风险评估</Text>
            </Col>
            <Col span={12} style={{ textAlign: 'right' }}>
              <Switch
                checked={values.include_risk !== false}
                onChange={(v) => update({ include_risk: v })}
                disabled={disabled}
              />
            </Col>
          </Row>

          <Divider style={{ margin: '12px 0', borderColor: 'rgba(255,255,255,0.06)' }} />

          <Row align="middle">
            <Col span={12}>
              <Text style={{ color: 'var(--text-primary)' }}>{AnalysisPhases.PHASE2.label}</Text>
            </Col>
            <Col span={12} style={{ textAlign: 'right' }}>
              <Switch
                checked={values.phase2_enabled}
                onChange={(v) => update({ phase2_enabled: v })}
                disabled={disabled}
              />
            </Col>
          </Row>
          {values.phase2_enabled && (
            <div>
              <Text style={{ color: 'var(--text-secondary)', fontSize: 12 }}>辩论轮数</Text>
              <Slider
                min={1}
                max={5}
                value={values.phase2_debate_rounds ?? 2}
                onChange={(v) => update({ phase2_debate_rounds: v })}
                disabled={disabled}
              />
            </div>
          )}

          <Row align="middle">
            <Col span={12}>
              <Text style={{ color: 'var(--text-primary)' }}>{AnalysisPhases.PHASE3.label}</Text>
            </Col>
            <Col span={12} style={{ textAlign: 'right' }}>
              <Switch
                checked={values.phase3_enabled}
                onChange={(v) => update({ phase3_enabled: v })}
                disabled={disabled}
              />
            </Col>
          </Row>
          {values.phase3_enabled && (
            <div>
              <Text style={{ color: 'var(--text-secondary)', fontSize: 12 }}>辩论轮数</Text>
              <Slider
                min={1}
                max={5}
                value={values.phase3_debate_rounds ?? 2}
                onChange={(v) => update({ phase3_debate_rounds: v })}
                disabled={disabled}
              />
            </div>
          )}

          <Row align="middle">
            <Col span={12}>
              <Text style={{ color: 'var(--text-primary)' }}>{AnalysisPhases.PHASE4.label}</Text>
            </Col>
            <Col span={12} style={{ textAlign: 'right' }}>
              <Switch
                checked={values.phase4_enabled}
                onChange={(v) => update({ phase4_enabled: v })}
                disabled={disabled}
              />
            </Col>
          </Row>
          {values.phase4_enabled && (
            <div>
              <Text style={{ color: 'var(--text-secondary)', fontSize: 12 }}>辩论轮数</Text>
              <Slider
                min={1}
                max={5}
                value={values.phase4_debate_rounds ?? 1}
                onChange={(v) => update({ phase4_debate_rounds: v })}
                disabled={disabled}
              />
            </div>
          )}

          <Divider style={{ margin: '12px 0', borderColor: 'rgba(255,255,255,0.06)' }} />

          <Input.TextArea
            value={values.custom_prompt}
            onChange={(e) => update({ custom_prompt: e.target.value })}
            placeholder="自定义分析提示词（可选）"
            disabled={disabled}
            autoSize={{ minRows: 2, maxRows: 4 }}
          />
        </Space>
      </Card>
    </Space>
  )
}
