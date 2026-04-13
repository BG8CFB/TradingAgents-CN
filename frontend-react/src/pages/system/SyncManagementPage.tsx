/**
 * 数据同步管理页面
 * 功能：数据源状态、同步控制、同步历史、连通性测试、使用建议
 */

import { useState, useEffect, useCallback } from 'react'
import {
  Card, Button, Space, Typography, Row, Col, Tag, Table,
  Spin, Alert, Progress, Popconfirm, message, Modal, Descriptions, Pagination,
  Empty,
} from 'antd'
import {
  SyncOutlined, ThunderboltOutlined,
  ReloadOutlined, HistoryOutlined,
  ApiOutlined, WarningOutlined, ExperimentOutlined,
} from '@ant-design/icons'
import type { ColumnsType } from 'antd/es/table'
import {
  getDataSourcesStatus,
  getCurrentDataSource,
  getStockBasicsStatus,
  runStockBasicsSync,
  runMultiSourceSync,
  testDataSources,
  getSyncRecommendations,
  getSyncHistory,
  type DataSourceStatusItem,
} from '@/services/api/sync'

const { Title, Text, Paragraph } = Typography

interface SyncHistoryRecord {
  started_at: string
  finished_at?: string
  status: string
  message?: string
  total_stocks?: number
  synced_stocks?: number
  errors?: number
  duration_seconds?: number
}

export default function SyncManagementPage() {
  // --- 数据源状态 ---
  const [sources, setSources] = useState<DataSourceStatusItem[]>([])
  const [currentSource, setCurrentSource] = useState<{ name: string; priority: number; description: string } | null>(null)
  const [sourcesLoading, setSourcesLoading] = useState(false)

  // --- 同步状态 ---
  const [syncStatus, setSyncStatus] = useState<Record<string, unknown> | null>(null)
  const [syncing, setSyncing] = useState(false)
  const [syncProgress, setSyncProgress] = useState(0)

  // --- 测试结果 ---
  const [testing, setTesting] = useState(false)
  const [testResults, setTestResults] = useState<Array<{
    name: string; priority: number; available: boolean; message: string
  }> | null>(null)
  const [testDialogOpen, setTestDialogOpen] = useState(false)

  // --- 历史记录 ---
  const [history, setHistory] = useState<SyncHistoryRecord[]>([])
  const [historyTotal, setHistoryTotal] = useState(0)
  const [historyPage, setHistoryPage] = useState(1)
  const [historyPageSize] = useState(10)

  // --- 建议 ---
  const [recommendations, setRecommendations] = useState<{
    primary_source: { name: string; priority: number } | null
    fallback_sources: Array<{ name: string; priority: number }>
    suggestions: string[]
    warnings: string[]
  } | null>(null)

  /** 加载数据源状态 */
  const loadSources = useCallback(async () => {
    setSourcesLoading(true)
    try {
      const [srcRes, curRes, recRes] = await Promise.all([
        getDataSourcesStatus(),
        getCurrentDataSource(),
        getSyncRecommendations(),
      ])
      setSources(Array.isArray(srcRes.data) ? srcRes.data : [])
      setCurrentSource(curRes.data ?? null)
      setRecommendations(recRes.data ?? null)
    } catch {
      message.error('加载数据源状态失败')
    } finally {
      setSourcesLoading(false)
    }
  }, [])

  /** 加载同步状态 */
  const loadSyncStatus = useCallback(async () => {
    try {
      const res = await getStockBasicsStatus()
      setSyncStatus(res.data as Record<string, unknown> ?? {})
    } catch {
      // ignore
    }
  }, [])

  /** 加载历史记录 */
  const loadHistory = useCallback(async (page = 1) => {
    try {
      const res = await getSyncHistory(page, historyPageSize)
      const histData = res.data as unknown as { records?: SyncHistoryRecord[]; total?: number } | undefined
      setHistory((histData?.records ?? []) as SyncHistoryRecord[])
      setHistoryTotal(histData?.total ?? 0)
    } catch {
      // ignore
    }
  }, [historyPageSize])

  useEffect(() => {
    loadSources()
    loadSyncStatus()
    loadHistory()
  }, [loadSources, loadSyncStatus, loadHistory])

  /** 触发基础数据同步 */
  const handleRunSync = async (force = false) => {
    setSyncing(true)
    setSyncProgress(0)
    // 模拟进度更新
    const progressTimer = setInterval(() => {
      setSyncProgress(prev => Math.min(prev + Math.random() * 15, 90))
    }, 1000)
    try {
      await runStockBasicsSync(force)
      message.success('同步任务已触发')
      await loadSyncStatus()
      await loadHistory(1)
      setSyncProgress(100)
    } catch (e: unknown) {
      const err = e as { response?: { data?: { detail?: string } }; message?: string }
      message.error(`同步失败: ${err?.response?.data?.detail || err?.message || '未知错误'}`)
    } finally {
      clearInterval(progressTimer)
      setSyncing(false)
      setTimeout(() => setSyncProgress(0), 1500)
    }
  }

  /** 触发多数据源同步 */
  const handleRunMultiSourceSync = async () => {
    setSyncing(true)
    try {
      await runMultiSourceSync(false)
      message.success('多数据源同步已触发')
      await loadSyncStatus()
      await loadHistory(1)
    } catch (e: unknown) {
      const err = e as { response?: { data?: { detail?: string } }; message?: string }
      message.error(`同步失败: ${err?.response?.data?.detail || err?.message || '未知错误'}`)
    } finally {
      setSyncing(false)
    }
  }

  /** 全面测试 */
  const handleFullTest = async () => {
    setTesting(true)
    setTestDialogOpen(true)
    try {
      const res = await testDataSources()
      const testData = res.data as { test_results?: Array<{ name: string; priority: number; available: boolean; message: string }> } | undefined
      setTestResults(testData?.test_results ?? null)
      const availableCount = (testData?.test_results ?? []).filter((r: { available: boolean }) => r.available).length
      message.success(`测试完成: ${availableCount}/${testData?.test_results?.length ?? 0} 数据源可用`)
    } catch {
      message.error('测试失败')
    } finally {
      setTesting(false)
    }
  }

  // ========== 历史表格列定义 ==========
  const historyColumns: ColumnsType<SyncHistoryRecord> = [
    {
      title: '开始时间',
      dataIndex: 'started_at',
      width: 170,
      render: (t: string) => new Date(t).toLocaleString(),
    },
    {
      title: '结束时间',
      dataIndex: 'finished_at',
      width: 170,
      render: (t: string | undefined) => t ? new Date(t).toLocaleString() : '-',
    },
    {
      title: '状态',
      dataIndex: 'status',
      width: 100,
      render: (s: string) => {
        const map: Record<string, { label: string; color: string }> = {
          success: { label: '成功', color: 'success' },
          failed: { label: '失败', color: 'error' },
          running: { label: '运行中', color: 'processing' },
          success_with_errors: { label: '部分成功', color: 'warning' },
        }
        const cfg = map[s] ?? { label: s, color: 'default' }
        return <Tag color={cfg.color}>{cfg.label}</Tag>
      },
    },
    {
      title: '同步数量',
      width: 120,
      render: (_, r) =>
        r.synced_stocks != null && r.total_stocks != null
          ? `${r.synced_stocks}/${r.total_stocks}`
          : '-',
    },
    {
      title: '错误数',
      dataIndex: 'errors',
      width: 80,
      render: (n: number | undefined) => n != null ? String(n) : '-',
    },
    {
      title: '耗时',
      dataIndex: 'duration_seconds',
      width: 80,
      render: (s: number | undefined) => s != null ? `${s.toFixed(1)}s` : '-',
    },
    {
      title: '消息',
      dataIndex: 'message',
      ellipsis: true,
      render: (m: string | undefined) => m || '-',
    },
  ]

  return (
    <div style={{ padding: '0 0 24px' }}>
      {/* 页面标题 */}
      <Card size="small" style={{ marginBottom: 16 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <Space>
            <Title level={4} style={{ margin: 0 }}>
              <SyncOutlined style={{ marginRight: 8 }} />
              多数据源同步管理
            </Title>
            <Text type="secondary" style={{ fontSize: 13 }}>
              管理和监控多个数据源的股票基础信息同步，支持自动 fallback 和优先级配置
            </Text>
          </Space>
          <Button
            type="primary"
            icon={<ExperimentOutlined />}
            loading={testing}
            onClick={handleFullTest}
          >
            全面测试
          </Button>
        </div>
      </Card>

      <Row gutter={24}>
        {/* 左侧：数据源状态 + 建议 */}
        <Col lg={12} xs={24}>
          {/* 数据源状态卡片 */}
          <Card
            title="数据源状态"
            size="small"
            extra={<Button size="small" icon={<ReloadOutlined />} onClick={loadSources} loading={sourcesLoading}>刷新</Button>}
            style={{ marginBottom: 16 }}
          >
            <Spin spinning={sourcesLoading}>
              {sources.length === 0 ? (
                <Empty description="暂无数据源配置" image={Empty.PRESENTED_IMAGE_SIMPLE} />
              ) : (
                <div>
                  {/* 当前使用的数据源 */}
                  {currentSource && (
                    <Alert
                      type="info"
                      showIcon
                      style={{ marginBottom: 12 }}
                      title={`当前数据源：${currentSource.name}`}
                      description={`优先级: ${currentSource.priority} | ${currentSource.description}`}
                    />
                  )}

                  {sources.map(src => (
                    <div
                      key={src.name}
                      style={{
                        display: 'flex', justifyContent: 'space-between', alignItems: 'center',
                        padding: '8px 12px', marginBottom: 8, borderRadius: 6,
                        border: `1px solid ${src.available ? '#d9f7be' : '#fff2f0'}`,
                        background: src.available ? '#f6ffed' : '#fff1f0',
                      }}
                    >
                      <Space>
                        <Tag color={src.available ? 'success' : 'error'}>{src.name.toUpperCase()}</Tag>
                        <Text type="secondary" style={{ fontSize: 12 }}>优先级: {src.priority}</Text>
                        {src.token_source && (
                          <Tag color="blue">Token: {src.token_source === 'database' ? '数据库' : '.env'}</Tag>
                        )}
                      </Space>
                      <span style={{
                        color: src.available ? '#52C41A' : '#FF4D4F',
                        fontWeight: 500, fontSize: 13,
                      }}>
                        {src.available ? '可用' : '不可用'}
                      </span>
                    </div>
                  ))}
                </div>
              )}
            </Spin>
          </Card>

          {/* 使用建议 */}
          {recommendations && (
            <Card title="使用建议" size="small">
              {recommendations.warnings.length > 0 && (
                <Alert
                  type="warning"
                  showIcon
                  icon={<WarningOutlined />}
                  style={{ marginBottom: 12 }}
                  title="注意事项"
                  description={
                    <ul style={{ margin: 0, paddingLeft: 16 }}>
                      {recommendations.warnings.map((w, i) => <li key={i}>{w}</li>)}
                    </ul>
                  }
                />
              )}
              {recommendations.suggestions.map((s, i) => (
                <Paragraph key={i} type="secondary" style={{ marginBottom: 4 }}>
                  - {s}
                </Paragraph>
              ))}
              {recommendations.primary_source && (
                <Alert
                  type="success"
                  showIcon
                  style={{ marginTop: 8 }}
                  title={`推荐主数据源：${recommendations.primary_source.name}（优先级 ${recommendations.primary_source.priority}）`}
                />
              )}
            </Card>
          )}
        </Col>

        {/* 右侧：同步控制 + 历史 */}
        <Col lg={12} xs={24}>
          {/* 同步控制 */}
          <Card
            title="同步控制"
            size="small"
            style={{ marginBottom: 16 }}
          >
            <Space orientation="vertical" style={{ width: '100%' }} size="middle">
              <div>
                <Text strong>股票基础数据同步</Text>
                <br />
                <Text type="secondary" style={{ fontSize: 12 }}>
                  触发全量同步，拉取所有 A 股基础信息（代码、名称、行业等）
                </Text>
              </div>

              {syncing && (
                <Progress percent={Math.round(syncProgress)} status="active" />
              )}

              <Space wrap>
                <Button
                  type="primary"
                  icon={<ThunderboltOutlined />}
                  loading={syncing}
                  onClick={() => handleRunSync(false)}
                >
                  开始同步
                </Button>
                <Popconfirm
                  title="强制同步将重新拉取所有数据，可能耗时较长。确定吗？"
                  onConfirm={() => handleRunSync(true)}
                  okText="确定"
                  cancelText="取消"
                >
                  <Button icon={<SyncOutlined />} disabled={syncing}>强制同步</Button>
                </Popconfirm>
                <Button
                  icon={<ApiOutlined />}
                  onClick={handleRunMultiSourceSync}
                  disabled={syncing}
                >
                  多源同步
                </Button>
              </Space>

              {/* 同步状态摘要 */}
              {syncStatus && typeof syncStatus === 'object' && (
                <Descriptions size="small" column={2} colon={false}>
                  {(Object.entries(syncStatus) as [string, unknown][]).slice(0, 6).map(([key, val]) => (
                    <Descriptions.Item key={key} label={key}>
                      {typeof val === 'object' ? JSON.stringify(val) : String(val ?? '-')}
                    </Descriptions.Item>
                  ))}
                </Descriptions>
              )}
            </Space>
          </Card>

          {/* 同步历史 */}
          <Card
            title="同步历史"
            size="small"
            extra={<Button size="small" icon={<HistoryOutlined />} onClick={() => loadHistory(1)}>刷新</Button>}
          >
            <Table
              dataSource={history}
              columns={historyColumns}
              rowKey="name"
              pagination={false}
              size="small"
              scroll={{ x: 700 }}
              locale={{ emptyText: '暂无同步记录' }}
            />
            {historyTotal > historyPageSize && (
              <Pagination
                current={historyPage}
                total={historyTotal}
                pageSize={historyPageSize}
                onChange={(p) => { setHistoryPage(p); loadHistory(p) }}
                size="small"
                style={{ textAlign: 'right', marginTop: 12 }}
                showTotal={(total) => `共 ${total} 条`}
              />
            )}
          </Card>
        </Col>
      </Row>

      {/* 测试结果对话框 */}
      <Modal
        title="全面测试结果"
        open={testDialogOpen}
        onCancel={() => setTestDialogOpen(false)}
        footer={<Button onClick={() => setTestDialogOpen(false)}>关闭</Button>}
        width={700}
      >
        {testResults ? (
          <div>
            <Alert
              type={testResults.some(r => !r.available) ? 'warning' : 'success'}
              showIcon
              title={`测试完成，共测试 ${testResults.length} 个数据源`}
              style={{ marginBottom: 16 }}
            />
            <Row gutter={[12, 12]}>
              {testResults.map(r => (
                <Col key={r.name} span={8}>
                  <Card size="small">
                    <Space orientation="vertical" size={0}>
                      <Tag color={r.available ? 'success' : 'error'} style={{ fontSize: 14, padding: '2px 8px' }}>
                        {r.name.toUpperCase()}
                      </Tag>
                      <Text type="secondary" style={{ fontSize: 11 }}>优先级: {r.priority}</Text>
                      <Alert
                        type={r.available ? 'success' : 'error'}
                        showIcon={false}
                        title={r.message}
                        style={{ marginTop: 4, padding: '4px 8px' }}
                      />
                    </Space>
                  </Card>
                </Col>
              ))}
            </Row>
          </div>
        ) : (
          <Spin />
        )}
      </Modal>
    </div>
  )
}
