import { useEffect, useState } from 'react'
import { Card, Typography, Row, Col, Statistic, Tag, Spin, Progress } from 'antd'
import {
  CheckCircleOutlined,
  ClockCircleOutlined,
  LoadingOutlined,
  WarningOutlined,
  ApiOutlined,
} from '@ant-design/icons'
import { getAnalysisStats, getUserQueueStatus, type AnalysisStats, type QueueStatus } from '@/services/api/analysis'

const { Text } = Typography

interface SystemStatusCardProps {
  refreshTrigger?: number
}

export default function SystemStatusCard({ refreshTrigger }: SystemStatusCardProps) {
  const [stats, setStats] = useState<AnalysisStats | null>(null)
  const [queue, setQueue] = useState<QueueStatus | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    Promise.all([
      getAnalysisStats({}, { skipErrorHandler: true }),
      getUserQueueStatus({ skipErrorHandler: true }),
    ])
      .then(([statsRes, queueRes]) => {
        setStats(statsRes.data ?? null)
        setQueue(queueRes.data ?? null)
      })
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [refreshTrigger])

  const successRate = stats?.total_analyses
    ? Math.round((stats.successful_analyses / stats.total_analyses) * 100)
    : 0

  const formatTokens = (tokens: number) => {
    if (tokens >= 1_000_000) return `${(tokens / 1_000_000).toFixed(1)}M`
    if (tokens >= 1_000) return `${(tokens / 1_000).toFixed(1)}K`
    return String(tokens)
  }

  const formatCost = (cost: number) => `¥${cost.toFixed(2)}`

  return (
    <Card
      title={
        <span style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <ApiOutlined style={{ color: 'var(--accent-primary)' }} />
          <span style={{ color: 'var(--text-primary)' }}>系统状态</span>
        </span>
      }
      style={{ background: 'var(--bg-card)', border: 'none' }}
      styles={{ header: { borderBottom: '1px solid var(--border-color)' } }}
    >
      <Spin spinning={loading}>
        <Row gutter={[24, 16]}>
          <Col xs={12} sm={6}>
            <Statistic
              title={<Text type="secondary" style={{ fontSize: 12 }}>总分析数</Text>}
              value={stats?.total_analyses ?? 0}
              styles={{ content: { color: 'var(--accent-primary)', fontSize: 22 } }}
            />
          </Col>
          <Col xs={12} sm={6}>
            <Statistic
              title={<Text type="secondary" style={{ fontSize: 12 }}>成功率</Text>}
              value={successRate}
              suffix="%"
              styles={{ content: {
                color: successRate >= 80 ? 'var(--accent-success)' : successRate >= 50 ? '#D48806' : (stats?.total_analyses ? 'var(--accent-error)' : 'var(--text-primary)'),
                fontSize: 22,
              } }}
            />
          </Col>
          <Col xs={12} sm={6}>
            <Statistic
              title={<Text type="secondary" style={{ fontSize: 12 }}>Token 消耗</Text>}
              value={formatTokens(stats?.total_tokens ?? 0)}
              styles={{ content: { color: 'var(--accent-blue)', fontSize: 22 } }}
            />
          </Col>
          <Col xs={12} sm={6}>
            <Statistic
              title={<Text type="secondary" style={{ fontSize: 12 }}>总花费</Text>}
              value={formatCost(stats?.total_cost ?? 0)}
              styles={{ content: { color: 'var(--text-primary)', fontSize: 22 } }}
            />
          </Col>
        </Row>

        {/* 队列状态 */}
        <div style={{ marginTop: 20, paddingTop: 16, borderTop: '1px solid var(--border-color)' }}>
          <Text type="secondary" style={{ fontSize: 12, marginBottom: 8, display: 'block' }}>任务队列</Text>
          {queue ? (
            <Row gutter={[12, 8]} align="middle">
              <Col>
                <Tag icon={<ClockCircleOutlined />} color="default">
                  待处理 {queue.pending}
                </Tag>
              </Col>
              <Col>
                <Tag icon={<LoadingOutlined spin />} color="processing">
                  处理中 {queue.processing}
                </Tag>
              </Col>
              <Col>
                <Tag icon={<CheckCircleOutlined />} color="success">
                  已完成 {queue.completed}
                </Tag>
              </Col>
              {queue.failed > 0 && (
                <Col>
                  <Tag icon={<WarningOutlined />} color="error">
                    失败 {queue.failed}
                  </Tag>
                </Col>
              )}
              <Col flex="auto">
                <Progress
                  percent={queue.total > 0 ? Math.round((queue.completed / queue.total) * 100) : 0}
                  size="small"
                  strokeColor={{ from: '#C9A96E', to: '#D4A574' }}
                  showInfo={false}
                />
              </Col>
            </Row>
          ) : (
            <Text type="secondary" style={{ fontSize: 12 }}>暂无队列数据</Text>
          )}
        </div>

        {/* 市场分布 */}
        {stats?.analysis_by_market && stats.analysis_by_market.length > 0 && (
          <div style={{ marginTop: 16, paddingTop: 16, borderTop: '1px solid var(--border-color)' }}>
            <Text type="secondary" style={{ fontSize: 12, marginBottom: 8, display: 'block' }}>市场分布</Text>
            <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap' }}>
              {stats.analysis_by_market.map((item: { market: string; count: number }) => (
                <Tag key={item.market} style={{ fontSize: 12 }}>
                  {item.market}: {item.count}
                </Tag>
              ))}
            </div>
          </div>
        )}
      </Spin>
    </Card>
  )
}
