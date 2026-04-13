import { useState, useEffect, useCallback } from 'react'
import {
  Card,
  Row,
  Col,
  Select,
  Statistic,
  Table,
  Typography,
  Spin,
  Button,
} from 'antd'
import {
  DollarOutlined,
  ThunderboltOutlined,
  FileTextOutlined,
  ReloadOutlined,
} from '@ant-design/icons'
import PieChart from '@/components/charts/PieChart'
import BarChart from '@/components/charts/BarChart'
import {
  getUsageStatistics,
  getCostByProvider,
  getCostByModel,
  getDailyCost,
  type UsageStatistics,
} from '@/services/api/usage'

const { Text } = Typography

const DAY_OPTIONS = [
  { value: 7, label: '近 7 天' },
  { value: 14, label: '近 14 天' },
  { value: 30, label: '近 30 天' },
  { value: 90, label: '近 90 天' },
]

export default function TokenStatisticsPage() {
  const [days, setDays] = useState(7)
  const [stats, setStats] = useState<UsageStatistics | null>(null)
  const [providerData, setProviderData] = useState<Array<{ name: string; value: number }>>([])
  const [modelData, setModelData] = useState<Array<{ name: string; value: number }>>([])
  const [dailyData, setDailyData] = useState<Array<{ name: string; value: number }>>([])
  const [loading, setLoading] = useState(false)

  const fetchData = useCallback(async () => {
    setLoading(true)
    try {
      const [statsRes, providerRes, modelRes, dailyRes] = await Promise.all([
        getUsageStatistics(days).catch(() => null),
        getCostByProvider(days).catch(() => null),
        getCostByModel(days).catch(() => null),
        getDailyCost(Math.min(days, 30)).catch(() => null),
      ])

      if (statsRes?.data) setStats(statsRes.data as UsageStatistics)

      if (providerRes?.data) {
        const pd = Object.entries(providerRes.data as Record<string, number | { cost?: number }>).map(([name, v]) => ({
          name,
          value: typeof v === 'number' ? v : v?.cost ?? 0,
        }))
        setProviderData(pd)
      }

      if (modelRes?.data) {
        const md = Object.entries(modelRes.data as Record<string, number | { cost?: number }>)
          .map(([name, v]) => ({ name, value: typeof v === 'number' ? v : v?.cost ?? 0 }))
          .sort((a, b) => b.value - a.value)
          .slice(0, 10)
        setModelData(md)
      }

      if (dailyRes?.data && Array.isArray(dailyRes.data)) {
        const dd = (dailyRes.data as Array<Record<string, unknown>>).map((item) => ({
          name: typeof item.date === 'string' ? item.date.slice(5, 10) : String(item.date ?? ''),
          value: Number(item.cost ?? 0),
        }))
        setDailyData(dd.reverse())
      }
    } finally {
      setLoading(false)
    }
  }, [days])

  useEffect(() => {
    fetchData()
  }, [fetchData])

  const formatTokens = (n: number) => {
    if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`
    if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`
    return String(n)
  }

  return (
    <div style={{ padding: '0 4px' }}>
      {/* 时间范围选择 */}
      <div style={{ marginBottom: 16, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <Select
          value={days}
          onChange={setDays}
          options={DAY_OPTIONS}
          style={{ width: 120 }}
        />
        <Button icon={<ReloadOutlined />} onClick={fetchData} loading={loading}>
          刷新
        </Button>
      </div>

      <Spin spinning={loading}>
        {/* 概览统计卡片 */}
        <Row gutter={[16, 16]} style={{ marginBottom: 16 }}>
          <Col xs={12} sm={6}>
            <Card size="small" style={{ background: 'var(--bg-card)', border: 'none' }}>
              <Statistic
                title={<Text type="secondary" style={{ fontSize: 12 }}>总请求数</Text>}
                value={stats?.total_requests ?? 0}
                prefix={<FileTextOutlined />}
                styles={{ content: { color: 'var(--accent-blue)', fontSize: 20 } }}
              />
            </Card>
          </Col>
          <Col xs={12} sm={6}>
            <Card size="small" style={{ background: 'var(--bg-card)', border: 'none' }}>
              <Statistic
                title={<Text type="secondary" style={{ fontSize: 12 }}>输入 Token</Text>}
                value={formatTokens(stats?.total_input_tokens ?? 0)}
                prefix={<ThunderboltOutlined />}
                styles={{ content: { color: 'var(--accent-primary)', fontSize: 20 } }}
              />
            </Card>
          </Col>
          <Col xs={12} sm={6}>
            <Card size="small" style={{ background: 'var(--bg-card)', border: 'none' }}>
              <Statistic
                title={<Text type="secondary" style={{ fontSize: 12 }}>输出 Token</Text>}
                value={formatTokens(stats?.total_output_tokens ?? 0)}
                prefix={<ThunderboltOutlined />}
                styles={{ content: { color: '#D4A574', fontSize: 20 } }}
              />
            </Card>
          </Col>
          <Col xs={12} sm={6}>
            <Card size="small" style={{ background: 'var(--bg-card)', border: 'none' }}>
              <Statistic
                title={<Text type="secondary" style={{ fontSize: 12 }}>总花费</Text>}
                value={`¥${(stats?.cost_by_currency?.CNY ?? stats?.total_cost ?? 0).toFixed(2)}`}
                prefix={<DollarOutlined />}
                styles={{ content: { color: 'var(--text-primary)', fontSize: 20 } }}
              />
            </Card>
          </Col>
        </Row>

        {/* 图表区域 */}
        <Row gutter={[16, 16]} style={{ marginBottom: 16 }}>
          <Col xs={24} lg={8}>
            <Card
              title="供应商成本分布"
              size="small"
              style={{ background: 'var(--bg-card)', border: 'none', height: '100%' }}
              styles={{ header: { borderBottom: '1px solid var(--border-color)' } }}
            >
              {providerData.length > 0 ? (
                <PieChart data={providerData} height={260} title="按供应商" showLegend />
              ) : (
                <div style={{ textAlign: 'center', color: 'var(--text-muted)', padding: 40 }}>暂无数据</div>
              )}
            </Card>
          </Col>
          <Col xs={24} lg={8}>
            <Card
              title="模型成本排名"
              size="small"
              style={{ background: 'var(--bg-card)', border: 'none', height: '100%' }}
              styles={{ header: { borderBottom: '1px solid var(--border-color)' } }}
            >
              {modelData.length > 0 ? (
                <BarChart data={modelData} height={260} horizontal showXAxisLabel={false} />
              ) : (
                <div style={{ textAlign: 'center', color: 'var(--text-muted)', padding: 40 }}>暂无数据</div>
              )}
            </Card>
          </Col>
          <Col xs={24} lg={8}>
            <Card
              title="每日成本趋势"
              size="small"
              style={{ background: 'var(--bg-card)', border: 'none', height: '100%' }}
              styles={{ header: { borderBottom: '1px solid var(--border-color)' } }}
            >
              {dailyData.length > 0 ? (
                <BarChart data={dailyData} height={260} />
              ) : (
                <div style={{ textAlign: 'center', color: 'var(--text-muted)', padding: 40 }}>暂无数据</div>
              )}
            </Card>
          </Col>
        </Row>

        {/* 按供应商/模型明细 */}
        {(stats?.by_provider || stats?.by_model) && (
          <Row gutter={[16, 16]}>
            {stats.by_provider && Object.keys(stats.by_provider).length > 0 && (
              <Col xs={24} lg={12}>
                <Card
                  title="供应商明细"
                  size="small"
                  style={{ background: 'var(--bg-card)', border: 'none' }}
                  styles={{ header: { borderBottom: '1px solid var(--border-color)' } }}
                >
                  <Table<Record<string, string | number>>
                    dataSource={Object.entries(stats.by_provider as Record<string, { requests?: number; tokens?: number; cost?: number }>).map(([name, v]) => ({
                      key: name,
                      provider: name,
                      requests: v.requests || 0,
                      tokens: formatTokens(v.tokens || 0),
                      cost: `¥${(v.cost || 0).toFixed(4)}`,
                    }))}
                    columns={[
                      { title: '供应商', dataIndex: 'provider', key: 'provider' },
                      { title: '请求数', dataIndex: 'requests', key: 'requests' },
                      { title: 'Token 数', dataIndex: 'tokens', key: 'tokens' },
                      { title: '花费', dataIndex: 'cost', key: 'cost' },
                    ]}
                    pagination={false}
                    size="small"
                  />
                </Card>
              </Col>
            )}
            {stats.by_model && Object.keys(stats.by_model).length > 0 && (
              <Col xs={24} lg={12}>
                <Card
                  title="模型明细"
                  size="small"
                  style={{ background: 'var(--bg-card)', border: 'none' }}
                  styles={{ header: { borderBottom: '1px solid var(--border-color)' } }}
                >
                  <Table<Record<string, string | number>>
                    dataSource={Object.entries(stats.by_model as Record<string, { requests?: number; tokens?: number; cost?: number }>)
                      .map(([name, v]) => ({
                        key: name,
                        model: name,
                        requests: v.requests || 0,
                        tokens: formatTokens(v.tokens || 0),
                        cost: `¥${(v.cost || 0).toFixed(4)}`,
                      }))
                      .sort((a, b) => parseFloat(String(b.cost).slice(1)) - parseFloat(String(a.cost).slice(1)))}
                    columns={[
                      { title: '模型名称', dataIndex: 'model', key: 'model', ellipsis: true },
                      { title: '请求数', dataIndex: 'requests', key: 'requests' },
                      { title: 'Token 数', dataIndex: 'tokens', key: 'tokens' },
                      { title: '花费', dataIndex: 'cost', key: 'cost' },
                    ]}
                    pagination={false}
                    size="small"
                  />
                </Card>
              </Col>
            )}
          </Row>
        )}
      </Spin>
    </div>
  )
}
