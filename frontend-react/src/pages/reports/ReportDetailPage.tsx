import { useState, useEffect } from 'react'
import { useSearchParams, useNavigate } from 'react-router-dom'
import {
  Card,
  Typography,
  Tag,
  Button,
  Space,
  Row, Col,
  Descriptions,
  Tabs,
  Spin,
  message,
  Progress,
  Empty,
} from 'antd'
import {
  ArrowLeftOutlined,
  DownloadOutlined,
  ShareAltOutlined,
  ClockCircleOutlined,
  FireOutlined,
  SafetyCertificateOutlined,
  ThunderboltOutlined,
} from '@ant-design/icons'
import { getReportDetail, getReportDownloadUrl, type ReportDetail } from '@/services/api/reports'
import MarkdownRenderer from '@/components/ui/MarkdownRenderer'

const { Title, Text, Paragraph } = Typography

const RISK_TAG_MAP: Record<string, { color: string; label: string }> = {
  low: { color: 'success', label: '低风险' },
  medium: { color: 'warning', label: '中风险' },
  high: { color: 'error', label: '高风险' },
  低: { color: 'success', label: '低风险' },
  中等: { color: 'warning', label: '中风险' },
  高: { color: 'error', label: '高风险' },
}

/** 模块名称映射到中文显示名 */
const MODULE_LABEL_MAP: Record<string, string> = {
  market_analyst_report: '市场分析',
  news_analyst_report: '新闻舆情',
  fundamentals_analyst_report: '基本面分析',
  technical_analyst_report: '技术面分析',
  sentiment_analyst_report: '情绪分析',
  macro_analyst_report: '宏观分析',
  bull_researcher: '多头研究',
  bear_researcher: '空头研究',
  research_team_decision: '研究团队决策',
  risky_analyst: '激进风控',
  safe_analyst: '保守风控',
  neutral_analyst: '中性风控',
  risk_management_decision: '风控决策',
  trader_investment_plan: '交易计划',
}

export default function ReportDetailPage() {
  const [searchParams] = useSearchParams()
  const navigate = useNavigate()
  const reportId = searchParams.get('id') || ''

  const [report, setReport] = useState<ReportDetail | null>(null)
  const [loading, setLoading] = useState(true)
  const [activeModule, setActiveModule] = useState('')

  useEffect(() => {
    if (!reportId) {
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setLoading(false)
      return
    }
    getReportDetail(reportId)
      .then((res) => {
        const data = res.data
        if (data) {
          setReport(data)
          // 默认选中第一个模块
          const modules = Object.keys(data.reports || {})
          if (modules.length > 0) setActiveModule(modules[0])
        }
      })
      .catch(() => message.error('获取报告详情失败'))
      .finally(() => setLoading(false))
  }, [reportId])

  if (!reportId) {
    return (
      <Card style={{ background: 'var(--bg-card)', border: 'none' }}>
        <Empty description="缺少报告 ID 参数" />
      </Card>
    )
  }

  const modules = Object.keys(report?.reports || {})
  const riskInfo = RISK_TAG_MAP[report?.risk_level || ''] || { color: 'default', label: report?.risk_level || '未知' }

  return (
    <div style={{ padding: '0 4px' }}>
      <Spin spinning={loading}>
        {/* 返回 + 操作栏 */}
        <div style={{ marginBottom: 16, display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <Button icon={<ArrowLeftOutlined />} onClick={() => navigate('/reports')}>
            返回列表
          </Button>
          <Space>
            <Button icon={<ShareAltOutlined />}>分享</Button>
            <Button
              type="primary"
              icon={<DownloadOutlined />}
              onClick={() => window.open(getReportDownloadUrl(reportId, 'markdown'), '_blank')}
            >
              下载报告
            </Button>
          </Space>
        </div>

        {!report ? (
          <Card style={{ background: 'var(--bg-card)', border: 'none' }}>
            <Empty description="报告不存在或已被删除" />
          </Card>
        ) : (
          <>
            {/* 报告头部信息 */}
            <Card style={{ background: 'var(--bg-card)', border: 'none', marginBottom: 16 }}>
              <Row gutter={[24, 16]} align="top">
                <Col xs={24} lg={16}>
                  <Title level={3} style={{ marginBottom: 8, color: 'var(--text-primary)' }}>
                    {report.stock_name}({report.stock_symbol}) 分析报告
                  </Title>
                  <Space size="middle" wrap>
                    <Tag>{(report as unknown as Record<string, unknown>).market_type as string ?? 'A股'}</Tag>
                    <Tag color={report.status === 'completed' ? 'success' : 'processing'}>
                      {report.status === 'completed' ? '已完成' : report.status}
                    </Tag>
                    <Tag color={riskInfo.color} icon={<SafetyCertificateOutlined />}>
                      {riskInfo.label}
                    </Tag>
                    <Text type="secondary" style={{ fontSize: 12 }}>
                      <ClockCircleOutlined style={{ marginRight: 4 }} />
                      {report.created_at?.slice(0, 19).replace('T', ' ')}
                    </Text>
                  </Space>

                  {report.summary && (
                    <Paragraph
                      style={{
                        marginTop: 12,
                        padding: '12px 16px',
                        background: 'var(--bg-base)',
                        borderRadius: 8,
                        borderLeft: '3px solid var(--accent-primary)',
                        fontSize: 14,
                        lineHeight: 1.8,
                        color: 'var(--text-secondary)',
                      }}
                    >
                      {report.summary}
                    </Paragraph>
                  )}
                </Col>

                <Col xs={24} lg={8}>
                  <Card
                    size="small"
                    title={<Text strong style={{ fontSize: 13 }}>核心指标</Text>}
                    style={{ background: 'var(--bg-base)', border: '1px solid var(--border-color)' }}
                    styles={{ header: { background: 'transparent', borderBottom: '1px solid var(--border-color)' } }}
                  >
                    <Descriptions column={1} size="small" styles={{ label: { color: 'var(--text-secondary)', fontSize: 12 } }}>
                      <Descriptions.Item label="置信度">
                        <Progress
                          percent={Math.round((report.confidence_score ?? 0) * 100)}
                          size="small"
                          strokeColor={report.confidence_score && report.confidence_score >= 0.7 ? '#52C41A' : '#D48806'}
                          format={(percent) => `${percent}%`}
                        />
                      </Descriptions.Item>
                      <Descriptions.Item label="投资建议">
                        <Text strong style={{ color: 'var(--accent-primary)', fontSize: 14 }}>
                          {report.recommendation || '-'}
                        </Text>
                      </Descriptions.Item>
                      <Descriptions.Item label="Token 消耗">
                        <FireOutlined style={{ color: 'var(--accent-blue)', marginRight: 4 }} />
                        <Text>{(report.tokens_used ?? 0).toLocaleString()}</Text>
                      </Descriptions.Item>
                      <Descriptions.Item label="执行耗时">
                        <ThunderboltOutlined style={{ color: 'var(--accent-primary)', marginRight: 4 }} />
                        <Text>{report.execution_time ? `${report.execution_time.toFixed(1)}s` : '-'}</Text>
                      </Descriptions.Item>
                      <Descriptions.Item label="分析师">
                        <Space size={[4, 4]} wrap>
                          {(report.analysts || []).map((a) => (
                            <Tag key={a} style={{ fontSize: 11 }}>{a}</Tag>
                          ))}
                        </Space>
                      </Descriptions.Item>
                    </Descriptions>
                  </Card>
                </Col>
              </Row>
            </Card>

            {/* 关键要点 */}
            {report.key_points && report.key_points.length > 0 && (
              <Card
                title="关键要点"
                style={{ background: 'var(--bg-card)', border: 'none', marginBottom: 16 }}
                styles={{ header: { borderBottom: '1px solid var(--border-color)' } }}
              >
                <ul style={{ paddingLeft: 20, margin: 0, color: 'var(--text-secondary)' }}>
                  {report.key_points.map((point, i) => (
                    <li key={i} style={{ marginBottom: 6, lineHeight: 1.6 }}>{point}</li>
                  ))}
                </ul>
              </Card>
            )}

            {/* 报告模块内容 */}
            {modules.length > 0 && (
              <Card
                style={{ background: 'var(--bg-card)', border: 'none' }}
                styles={{ body: { padding: 0 } }}
              >
                <Tabs
                  activeKey={activeModule}
                  onChange={setActiveModule}
                  items={modules.map((key) => ({
                    key,
                    label: MODULE_LABEL_MAP[key] || key.replace(/_report$/, '').replace(/_/g, ' '),
                    children: (
                      <div style={{ padding: '16px 20px' }}>
                        <MarkdownRenderer content={report!.reports[key]} />
                      </div>
                    ),
                  }))}
                  style={{ padding: '0 16px' }}
                />
              </Card>
            )}

            {modules.length === 0 && (
              <Card style={{ background: 'var(--bg-card)', border: 'none' }}>
                <Empty description="暂无报告模块内容" />
              </Card>
            )}
          </>
        )}
      </Spin>
    </div>
  )
}
