/**
 * 使用统计页面
 * Token 使用量、成本统计、按供应商/模型/日期维度展示图表
 */

import { useState, useEffect, useCallback, useRef } from 'react'
import {
  Card, Row, Col, Statistic, Table, Select, Space,
  Typography, Empty, Button,
} from 'antd'
import {
  ReloadOutlined, ThunderboltOutlined,
} from '@ant-design/icons'
import type { ColumnsType } from 'antd/es/table'
import {
  getUsageStatistics, getCostByProvider, getCostByModel, getDailyCost, getUsageRecords,
} from '@/services/api/usage'
import type { UsageStatistics, UsageRecord } from '@/services/api/usage'
import PieChart from '@/components/charts/PieChart'
import BarChart from '@/components/charts/BarChart'

const { Text, Title } = Typography

export default function UsageStatisticsPage() {
  const [days, setDays] = useState(7)
  const [loading, setLoading] = useState(false)

  const [statistics, setStatistics] = useState<UsageStatistics | null>(null)
  const [costByProvider, setCostByProvider] = useState<Record<string, { cost: number; count: number }> | null>(null)
  const [costByModel, setCostByModel] = useState<Record<string, { cost: number; count: number }> | null>(null)
  const [dailyCost, setDailyCost] = useState<Array<{ date: string; cost: number; tokens: number }>>([])
  const [records, setRecords] = useState<UsageRecord[]>([])

  const loadingRef = useRef(false)
  const loadData = useCallback(async () => {
    if (loadingRef.current) return
    loadingRef.current = true
    setLoading(true)
    try {
      const [statsRes, providerRes, modelRes, dailyRes] = await Promise.all([
        getUsageStatistics(days).catch(() => null),
        getCostByProvider(days).catch(() => null),
        getCostByModel(days).catch(() => null),
        getDailyCost(30).catch(() => ({ data: [] })),
      ])
      setStatistics(statsRes?.data ?? null)
      setCostByProvider(providerRes?.data ?? null)
      setCostByModel(modelRes?.data ?? null)
      setDailyCost(Array.isArray(dailyRes?.data) ? dailyRes.data : [])
    } finally {
      setLoading(false)
      loadingRef.current = false
    }
  }, [days])

  useEffect(() => { loadData() }, [days, loadData])

  /** 加载详细记录 */
  const loadRecords = async (provider?: string, model?: string) => {
    setLoading(true)
    try {
      const params: Parameters<typeof getUsageRecords>[0] = {}
      if (provider) params.provider = provider
      if (model) params.model_name = model
      const res = await getUsageRecords(params)
      setRecords(res.data.records ?? [])
    } finally {
      setLoading(false)
    }
  }

  // 饼图数据：按供应商
  const providerPieData = costByProvider
    ? Object.entries(costByProvider).map(([name, data]) => ({
        name,
        value: data.cost,
      }))
    : []

  // 饼图数据：按模型
  const modelPieData = costByModel
    ? Object.entries(costByModel).map(([name, data]) => ({
        name,
        value: data.cost,
      }))
    : []

  // 柱状图数据：每日成本
  const dailyBarData = dailyCost.map(d => ({
    name: d.date.slice(5), // 只显示 MM-DD
    value: Number(d.cost.toFixed(4)),
  }))

  const recordColumns: ColumnsType<UsageRecord> = [
    { title: '时间', dataIndex: 'timestamp', width: 160, render: t => new Date(t).toLocaleString() },
    { title: '供应商', dataIndex: 'provider', width: 120 },
    { title: '模型', dataIndex: 'model_name', width: 180, render: t => <Text code>{t}</Text> },
    { title: '输入 Tokens', dataIndex: 'input_tokens', width: 110, align: 'right' },
    { title: '输出 Tokens', dataIndex: 'output_tokens', width: 110, align: 'right' },
    { title: '费用', dataIndex: 'cost', width: 100, align: 'right', render: v => `¥${Number(v).toFixed(4)}` },
    { title: '类型', dataIndex: 'analysis_type', width: 120 },
  ]

  return (
    <div>
      <Title level={4} style={{ marginBottom: 20 }}>使用统计</Title>

      {/* 时间范围选择 */}
      <Card size="small" style={{ marginBottom: 16 }}>
        <Space>
          <Text>统计范围：</Text>
          <Select
            value={days}
            onChange={setDays}
            style={{ width: 120 }}
            options={[
              { value: 7, label: '最近 7 天' },
              { value: 14, label: '最近 14 天' },
              { value: 30, label: '最近 30 天' },
              { value: 90, label: '最近 90 天' },
            ]}
          />
          <Button icon={<ReloadOutlined />} onClick={loadData} loading={loading}>刷新</Button>
        </Space>
      </Card>

      {/* 总览统计 */}
      <Row gutter={16} style={{ marginBottom: 20 }}>
        <Col span={6}>
          <Card size="small">
            <Statistic
              title="总请求数"
              value={statistics?.total_requests ?? 0}
              prefix={<ThunderboltOutlined />}
              loading={loading}
            />
          </Card>
        </Col>
        <Col span={6}>
          <Card size="small">
            <Statistic
              title="输入 Tokens"
              value={statistics?.total_input_tokens ?? 0}
              formatter={(v) => ((Number(v) / 10000).toFixed(1) + '万')}
              loading={loading}
            />
          </Card>
        </Col>
        <Col span={6}>
          <Card size="small">
            <Statistic
              title="输出 Tokens"
              value={statistics?.total_output_tokens ?? 0}
              formatter={(v) => ((Number(v) / 10000).toFixed(1) + '万')}
              loading={loading}
            />
          </Card>
        </Col>
        <Col span={6}>
          <Card size="small">
            <Statistic
              title="总花费"
              value={statistics?.total_cost ?? 0}
              precision={4}
              prefix="¥"
              loading={loading}
              styles={{ content: { color: '#52c41a', fontWeight: 700 } }}
            />
          </Card>
        </Col>
      </Row>

      {/* 图表区域 */}
      <Row gutter={16} style={{ marginBottom: 20 }}>
        <Col span={12}>
          <Card size="small" title={`按供应商分布（近 ${days} 天）`}>
            {providerPieData.length > 0 ? (
              <PieChart data={providerPieData} height={280} />
            ) : (
              <Empty description="暂无数据" image={Empty.PRESENTED_IMAGE_SIMPLE} />
            )}
          </Card>
        </Col>
        <Col span={12}>
          <Card size="small" title={`按模型分布（近 ${days} 天）`}>
            {modelPieData.length > 0 ? (
              <PieChart data={modelPieData} height={280} />
            ) : (
              <Empty description="暂无数据" image={Empty.PRESENTED_IMAGE_SIMPLE} />
            )}
          </Card>
        </Col>
      </Row>

      {/* 每日趋势 */}
      <Card size="small" title="每日成本趋势（近 30 天）" style={{ marginBottom: 20 }}>
        {dailyBarData.length > 0 ? (
          <BarChart
            data={dailyBarData}
            height={260}
          />
        ) : (
          <Empty description="暂无数据" image={Empty.PRESENTED_IMAGE_SIMPLE} />
        )}
      </Card>

      {/* 详细记录 */}
      <Card
        size="small"
        title="使用记录明细"
        extra={
          <Button size="small" onClick={() => loadRecords()} loading={loading}>
            加载记录
          </Button>
        }
      >
        <Table<UsageRecord>
          dataSource={records}
          columns={recordColumns}
          rowKey={(record) => record.id ?? `${record.timestamp}-${record.model_name}`}
          loading={loading}
          pagination={{ pageSize: 15 }}
          size="small"
          locale={{ emptyText: '点击"加载记录"查看详细使用记录' }}
          scroll={{ x: 900 }}
        />
      </Card>
    </div>
  )
}
