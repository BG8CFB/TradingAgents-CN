import { useState } from 'react'
import { Card, Button, Row, Col, Typography, Alert, Space, Input, Tag, message } from 'antd'
import { RocketOutlined, ReloadOutlined } from '@ant-design/icons'
import { useAnalysisSubmit } from '@/features/analysis/hooks/useAnalysisSubmit'
import BatchStockInput from '@/features/analysis/components/BatchStockInput'
import MarketSelector from '@/features/analysis/components/MarketSelector'
import AnalysisConfigForm from '@/features/analysis/components/AnalysisConfigForm'
import AnalysisProgressBar from '@/features/analysis/components/AnalysisProgressBar'
import TaskStatusBadge from '@/features/analysis/components/TaskStatusBadge'
import type { AnalysisConfigFormValues } from '@/features/analysis/components/AnalysisConfigForm'

const { Title, Text } = Typography

export default function BatchAnalysisPage() {
  const [title, setTitle] = useState('')
  const [description, setDescription] = useState('')
  const [symbols, setSymbols] = useState<string[]>([])
  const [market, setMarket] = useState('CN')
  const [config, setConfig] = useState<AnalysisConfigFormValues>({
    research_depth: 'quick',
    selected_analysts: [],
    include_sentiment: true,
    include_risk: true,
    phase2_enabled: false,
    phase2_debate_rounds: 2,
    phase3_enabled: false,
    phase3_debate_rounds: 2,
    phase4_enabled: false,
    phase4_debate_rounds: 1,
  })

  const { submitBatch, loading: submitting, error: submitError, batchData, reset: resetSubmit } = useAnalysisSubmit()

  const handleSubmit = async () => {
    if (symbols.length === 0) {
      message.warning('请输入至少一个股票代码')
      return
    }
    if (!title.trim()) {
      message.warning('请输入批次标题')
      return
    }
    const success = await submitBatch({
      title: title.trim(),
      description: description.trim() || undefined,
      symbols,
      parameters: {
        market_type: market,
        ...config,
        selected_analysts: config.selected_analysts || [],
      },
    })
    if (success) {
      message.success('批量分析任务已提交')
    }
  }

  const handleReset = () => {
    setTitle('')
    setDescription('')
    setSymbols([])
    setMarket('CN')
    setConfig({
      research_depth: 'quick',
      selected_analysts: [],
      include_sentiment: true,
      include_risk: true,
      phase2_enabled: false,
      phase2_debate_rounds: 2,
      phase3_enabled: false,
      phase3_debate_rounds: 2,
      phase4_enabled: false,
      phase4_debate_rounds: 1,
    })
    resetSubmit()
  }

  const hasBatch = !!batchData

  return (
    <div style={{ color: 'var(--text-primary)' }}>
      <Title level={3} style={{ color: 'var(--text-primary)', marginBottom: 24 }}>
        批量分析
      </Title>

      <Row gutter={[24, 24]}>
        <Col xs={24} lg={10}>
          <Card
            title={<span style={{ color: 'var(--text-primary)' }}>批次配置</span>}
            style={{ background: 'var(--bg-card)', border: 'none' }}
            styles={{ header: { borderBottom: '1px solid rgba(255,255,255,0.06)' } }}
          >
            <Space vertical size="middle" style={{ width: '100%' }}>
              <div>
                <Text style={{ color: 'var(--text-secondary)' }}>批次标题</Text>
                <Input
                  value={title}
                  onChange={(e) => setTitle(e.target.value)}
                  placeholder="如：科技板块批量分析"
                  disabled={submitting}
                  style={{ marginTop: 8 }}
                />
              </div>

              <div>
                <Text style={{ color: 'var(--text-secondary)' }}>批次描述</Text>
                <Input.TextArea
                  value={description}
                  onChange={(e) => setDescription(e.target.value)}
                  placeholder="可选描述"
                  disabled={submitting}
                  autoSize={{ minRows: 2, maxRows: 3 }}
                  style={{ marginTop: 8 }}
                />
              </div>

              <div>
                <Text style={{ color: 'var(--text-secondary)' }}>市场类型</Text>
                <div style={{ marginTop: 8 }}>
                  <MarketSelector value={market} onChange={setMarket} disabled={submitting} />
                </div>
              </div>

              <div>
                <Text style={{ color: 'var(--text-secondary)' }}>股票代码列表</Text>
                <div style={{ marginTop: 8 }}>
                  <BatchStockInput
                    values={symbols}
                    onChange={setSymbols}
                    market={market}
                    disabled={submitting}
                  />
                </div>
              </div>

              <AnalysisConfigForm
                values={config}
                onChange={setConfig}
                disabled={submitting}
              />

              {submitError && (
                <Alert title={submitError} type="error" showIcon />
              )}

              <Space style={{ width: '100%', justifyContent: 'flex-end', marginTop: 8 }}>
                <Button onClick={handleReset} disabled={submitting}>
                  重置
                </Button>
                <Button
                  type="primary"
                  icon={<RocketOutlined />}
                  loading={submitting}
                  onClick={handleSubmit}
                  style={{
                    background: 'var(--accent-primary)',
                    borderColor: 'var(--accent-primary)',
                    boxShadow: '0 2px 12px rgba(201,169,110,0.2)',
                  }}
                >
                  开始批量分析
                </Button>
              </Space>
            </Space>
          </Card>
        </Col>

        <Col xs={24} lg={14}>
          {hasBatch ? (
            <Card
              title={<span style={{ color: 'var(--text-primary)' }}>批次进度</span>}
              style={{ background: 'var(--bg-card)', border: 'none' }}
              styles={{ header: { borderBottom: '1px solid rgba(255,255,255,0.06)' } }}
            >
              <Space vertical size="large" style={{ width: '100%' }}>
                <div>
                  <Text strong style={{ color: 'var(--text-primary)' }}>{title || '批量分析批次'}</Text>
                  <div style={{ marginTop: 4 }}>
                    <Tag color="default">共 {batchData.total_tasks} 个任务</Tag>
                    <Tag color="processing">状态: {batchData.status}</Tag>
                  </div>
                </div>

                <AnalysisProgressBar progress={0} status="active" />

                <div
                  style={{
                    border: '1px solid rgba(255,255,255,0.08)',
                    borderRadius: 4,
                    background: 'transparent',
                  }}
                >
                  {(batchData.mapping || []).map((item, idx) => (
                    <div
                      key={`${item.symbol}-${idx}`}
                      style={{
                        borderBottom: '1px solid rgba(255,255,255,0.08)',
                        padding: '8px 12px',
                        display: 'flex',
                        alignItems: 'center',
                      }}
                    >
                      <Space>
                        <Text style={{ color: 'var(--text-primary)', minWidth: 80 }}>{item.symbol}</Text>
                        <TaskStatusBadge status={batchData.status} />
                      </Space>
                    </div>
                  ))}
                </div>

                <Button icon={<ReloadOutlined />} onClick={handleReset}>
                  新建批次
                </Button>
              </Space>
            </Card>
          ) : (
            <Card
              style={{
                background: 'var(--bg-card)',
                border: 'none',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                minHeight: 320,
              }}
            >
              <div style={{ textAlign: 'center', color: 'var(--text-secondary)' }}>
                <RocketOutlined style={{ fontSize: 48, marginBottom: 16, opacity: 0.5 }} />
                <div>提交批量分析任务后，这里将显示批次进度</div>
              </div>
            </Card>
          )}
        </Col>
      </Row>
    </div>
  )
}
