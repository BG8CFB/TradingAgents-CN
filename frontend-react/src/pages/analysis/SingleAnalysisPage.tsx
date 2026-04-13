import { useState } from 'react'
import { Card, Button, Row, Col, Typography, Alert, Space, Tag, message } from 'antd'
import { RocketOutlined, ReloadOutlined } from '@ant-design/icons'
import { useAnalysisSubmit } from '@/features/analysis/hooks/useAnalysisSubmit'
import { useAnalysisProgress } from '@/features/analysis/hooks/useAnalysisProgress'
import StockCodeInput from '@/features/analysis/components/StockCodeInput'
import MarketSelector from '@/features/analysis/components/MarketSelector'
import AnalysisConfigForm from '@/features/analysis/components/AnalysisConfigForm'
import AnalysisProgressBar from '@/features/analysis/components/AnalysisProgressBar'
import AnalysisStepTimeline from '@/features/analysis/components/AnalysisStepTimeline'
import AnalysisResultView from '@/features/analysis/components/AnalysisResultView'
import type { AnalysisConfigFormValues } from '@/features/analysis/components/AnalysisConfigForm'
import dayjs from 'dayjs'

const { Title, Text } = Typography

export default function SingleAnalysisPage() {
  const [symbol, setSymbol] = useState('')
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

  const { submitSingle, loading: submitting, error: submitError, taskId, reset: resetSubmit } = useAnalysisSubmit()
  const { progress, status, currentStep, stepDetail, result, isRunning, error: progressError, isConnected } =
    useAnalysisProgress({ taskId: taskId || undefined })

  const handleSubmit = async () => {
    if (!symbol.trim()) {
      message.warning('请输入股票代码')
      return
    }
    const success = await submitSingle({
      symbol: symbol.trim(),
      parameters: {
        market_type: market,
        analysis_date: dayjs().format('YYYY-MM-DD'),
        ...config,
        selected_analysts: config.selected_analysts || [],
      },
    })
    if (success) {
      message.success('分析任务已提交')
    }
  }

  const handleReset = () => {
    setSymbol('')
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

  const showResult = result && status === 'completed'
  const showProgress = isRunning || status === 'completed' || status === 'failed' || status === 'cancelled'

  return (
    <div style={{ color: 'var(--text-primary)' }}>
      <Title level={3} style={{ color: 'var(--text-primary)', marginBottom: 24 }}>
        单股分析
      </Title>

      <Row gutter={[24, 24]}>
        <Col xs={24} lg={10}>
          <Card
            title={<span style={{ color: 'var(--text-primary)' }}>分析配置</span>}
            style={{ background: 'var(--bg-card)', border: 'none' }}
            styles={{ header: { borderBottom: '1px solid rgba(255,255,255,0.06)' } }}
          >
            <Space vertical size="middle" style={{ width: '100%' }}>
              <div>
                <Text style={{ color: 'var(--text-secondary)' }}>市场类型</Text>
                <div style={{ marginTop: 8 }}>
                  <MarketSelector value={market} onChange={setMarket} disabled={submitting || isRunning} />
                </div>
              </div>

              <div>
                <Text style={{ color: 'var(--text-secondary)' }}>股票代码</Text>
                <div style={{ marginTop: 8 }}>
                  <StockCodeInput
                    value={symbol}
                    onChange={setSymbol}
                    market={market}
                    disabled={submitting || isRunning}
                  />
                </div>
              </div>

              <AnalysisConfigForm
                values={config}
                onChange={setConfig}
                disabled={submitting || isRunning}
              />

              {submitError && (
                <Alert title={submitError} type="error" showIcon />
              )}

              <Space style={{ width: '100%', justifyContent: 'flex-end', marginTop: 8 }}>
                <Button onClick={handleReset} disabled={submitting || isRunning}>
                  重置
                </Button>
                <Button
                  type="primary"
                  icon={<RocketOutlined />}
                  loading={submitting}
                  disabled={isRunning}
                  onClick={handleSubmit}
                  style={{
                    background: 'var(--accent-primary)',
                    borderColor: 'var(--accent-primary)',
                    boxShadow: '0 2px 12px rgba(201,169,110,0.2)',
                  }}
                >
                  开始分析
                </Button>
              </Space>
            </Space>
          </Card>
        </Col>

        <Col xs={24} lg={14}>
          {showProgress ? (
            <Card
              title={<span style={{ color: 'var(--text-primary)' }}>分析进度</span>}
              style={{ background: 'var(--bg-card)', border: 'none' }}
              styles={{ header: { borderBottom: '1px solid rgba(255,255,255,0.06)' } }}
              extra={
                isConnected ? (
                  <Tag color="success">实时连接中</Tag>
                ) : isRunning ? (
                  <Tag>连接中...</Tag>
                ) : null
              }
            >
              <Space vertical size="large" style={{ width: '100%' }}>
                <AnalysisProgressBar progress={progress} status={isRunning ? 'active' : status === 'completed' ? 'success' : 'exception'} />

                <div>
                  <Text strong style={{ color: 'var(--text-primary)' }}>{currentStep || status}</Text>
                  {stepDetail && (
                    <div style={{ color: 'var(--text-secondary)', marginTop: 4 }}>{stepDetail}</div>
                  )}
                </div>

                {progressError && (
                  <Alert title={progressError} type="error" showIcon />
                )}

                <AnalysisStepTimeline currentStepName={currentStep} />

                {!isRunning && status !== 'completed' && (
                  <Button icon={<ReloadOutlined />} onClick={handleReset}>
                    重新分析
                  </Button>
                )}
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
                <div>提交分析任务后，这里将显示实时进度</div>
              </div>
            </Card>
          )}

          {showResult && result && (
            <Card
              title={<span style={{ color: 'var(--text-primary)' }}>分析结果</span>}
              style={{ marginTop: 24, background: 'var(--bg-card)', border: 'none' }}
              styles={{ header: { borderBottom: '1px solid rgba(255,255,255,0.06)' } }}
            >
              <AnalysisResultView result={result} />
            </Card>
          )}
        </Col>
      </Row>
    </div>
  )
}
