/**
 * 操作日志管理页面
 * 功能：日志列表（分页/筛选）、统计概览、详情查看、清空日志
 */

import { useState, useEffect, useCallback, useRef } from 'react'
import {
  Card, Button, Space, Typography, Table, Tag, DatePicker,
  Select, Input, Row, Col, Statistic, Modal, Descriptions,
  Popconfirm, message, Empty, Tooltip, Spin, Alert,
} from 'antd'
import {
  FileSearchOutlined, ReloadOutlined, DeleteOutlined,
  EyeOutlined, BarChartOutlined, FilterOutlined,
  WarningOutlined, CheckCircleOutlined, CloseCircleOutlined,
} from '@ant-design/icons'
import type { ColumnsType } from 'antd/es/table'
import dayjs from 'dayjs'
import {
  getOperationLogs,
  getOperationLogStats,
  getOperationLogDetail,
  clearOperationLogs,
  type OperationLogItem,
  type OperationLogStats,
  type OperationLogListResponse,
} from '@/services/api/operation-logs'

const { Title, Text } = Typography
const { RangePicker } = DatePicker

/** 操作类型选项 */
const ACTION_TYPE_OPTIONS = [
  { value: '', label: '全部' },
  { value: 'login', label: '登录' },
  { value: 'logout', label: '登出' },
  { value: 'create', label: '创建' },
  { value: 'update', label: '更新' },
  { value: 'delete', label: '删除' },
  { value: 'query', label: '查询' },
  { value: 'export', label: '导出' },
  { value: 'import', label: '导入' },
  { value: 'sync', label: '同步' },
  { value: 'analysis', label: '分析' },
]

/** 操作类型中文映射 */
const ACTION_TYPE_LABELS: Record<string, string> = {
  login: '登录',
  logout: '登出',
  create: '创建',
  update: '更新',
  delete: '删除',
  query: '查询',
  export: '导出',
  import: '导入',
  sync: '同步',
  analysis: '分析',
}

export default function OperationLogsPage() {
  // --- 列表数据 ---
  const [logs, setLogs] = useState<OperationLogItem[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(20)
  const [loading, setLoading] = useState(false)

  // --- 筛选条件 ---
  const [actionType, setActionType] = useState<string>('')
  const [successFilter, setSuccessFilter] = useState<boolean | undefined>(undefined)
  const [dateRange, setDateRange] = useState<[dayjs.Dayjs, dayjs.Dayjs] | null>(null)
  const [keyword, setKeyword] = useState('')

  // --- 统计数据 ---
  const [stats, setStats] = useState<OperationLogStats | null>(null)

  // --- 详情弹窗 ---
  const [detailOpen, setDetailOpen] = useState(false)
  const [currentLog, setCurrentLog] = useState<OperationLogItem | null>(null)
  const [detailLoading, setDetailLoading] = useState(false)

  // --- 清空操作 ---
  const [clearing, setClearing] = useState(false)

  /** 加载日志列表 — 接受显式参数，不依赖闭包中的状态 */
  const loadLogs = useCallback(async (
    opts?: { p?: number; ps?: number; at?: string; sf?: boolean | undefined; kw?: string; dr?: [dayjs.Dayjs, dayjs.Dayjs] | null },
  ) => {
    setLoading(true)
    try {
      const { p = 1, ps = pageSize, at = actionType, sf = successFilter, kw = keyword, dr = dateRange } = opts ?? {}
      const params: Record<string, unknown> = { page: p, page_size: ps }
      if (at) params.action_type = at
      if (sf !== undefined) params.success = sf
      if (kw) params.keyword = kw.trim()
      if (dr) {
        params.start_date = dr[0].format('YYYY-MM-DD')
        params.end_date = dr[1].format('YYYY-MM-DD')
      }
      const res = await getOperationLogs(params as Parameters<typeof getOperationLogs>[0])
      const data = res.data ?? {} as OperationLogListResponse
      setLogs(data.logs ?? [])
      setTotal(data.total ?? 0)
    } catch {
      message.error('加载操作日志失败')
    } finally {
      setLoading(false)
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pageSize]) // 仅依赖 pageSize（稳定值），筛选参数通过参数传入

  /** 加载统计数据 */
  const loadStats = useCallback(async () => {
    try {
      const res = await getOperationLogStats(30)
      setStats(res.data ?? null)
    } catch {
      // 统计加载失败不阻塞主流程
    }
  }, [])

  // 首次加载（ guarded 防止 StrictMode 双调）
  const initializedRef = useRef(false)
  useEffect(() => {
    if (initializedRef.current) return
    initializedRef.current = true
    loadLogs()
    loadStats()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  /** 查看详情 */
  const handleViewDetail = async (log: OperationLogItem) => {
    setCurrentLog(log)
    setDetailOpen(true)
    // 如果没有 details 字段，尝试从后端获取完整详情
    if (!log.details || Object.keys(log.details).length === 0) {
      setDetailLoading(true)
      try {
        const res = await getOperationLogDetail(log.id)
        setCurrentLog(res.data ?? log)
      } catch {
        // 使用已有数据展示
      } finally {
        setDetailLoading(false)
      }
    }
  }

  /** 筛选条件变化时重置到第一页并加载 */
  const handleFilterChange = () => {
    setPage(1)
    // 显式传入当前筛选状态（React 18 批处理中 setState 尚未生效时也能拿到正确值）
    loadLogs({ p: 1, at: actionType, sf: successFilter, kw: keyword, dr: dateRange })
  }

  /** 分页变化 */
  const handlePageChange = (p: number, ps?: number) => {
    const newPageSize = ps ?? pageSize
    setPage(p)
    if (ps && ps !== pageSize) setPageSize(ps)
    loadLogs({ p, ps: newPageSize })
  }

  /** 重置筛选 */
  const handleReset = () => {
    setActionType('')
    setSuccessFilter(undefined)
    setDateRange(null)
    setKeyword('')
    setPage(1)
    loadLogs({ p: 1 })
  }

  /** 清空日志 */
  const handleClear = async () => {
    setClearing(true)
    try {
      const res = await clearOperationLogs(undefined, actionType || undefined)
      const count = (res.data as { deleted_count?: number })?.deleted_count ?? 0
      message.success(`已清理 ${count} 条日志`)
      setPage(1) // 清空后重置到第 1 页
      loadLogs({ p: 1 })
      loadStats()
    } catch {
      message.error('清理失败')
    } finally {
      setClearing(false)
    }
  }

  // ========== 表格列定义 ==========
  const columns: ColumnsType<OperationLogItem> = [
    {
      title: '时间',
      dataIndex: 'timestamp',
      width: 170,
      sorter: true,
      render: (t: string) => (
        <Tooltip title={new Date(t).toLocaleString()}>
          <span className="font-mono" style={{ fontSize: 12 }}>
            {new Date(t).toLocaleString()}
          </span>
        </Tooltip>
      ),
    },
    {
      title: '用户',
      dataIndex: 'username',
      width: 100,
      render: (u: string) => u || '-',
    },
    {
      title: '操作类型',
      dataIndex: 'action_type',
      width: 100,
      render: (type: string) => (
        <Tag color="blue" style={{ marginRight: 0 }}>
          {ACTION_TYPE_LABELS[type] || type}
        </Tag>
      ),
    },
    {
      title: '操作描述',
      dataIndex: 'action',
      ellipsis: true,
      render: (a: string) => a || '-',
    },
    {
      title: '状态',
      dataIndex: 'success',
      width: 80,
      render: (ok: boolean) => (
        <Tag
          icon={ok ? <CheckCircleOutlined /> : <CloseCircleOutlined />}
          color={ok ? 'success' : 'error'}
          style={{ marginRight: 0 }}
        >
          {ok ? '成功' : '失败'}
        </Tag>
      ),
    },
    {
      title: '耗时',
      dataIndex: 'duration_ms',
      width: 80,
      render: (ms: number | undefined) =>
        ms != null ? `${ms}ms` : '-',
    },
    {
      title: 'IP 地址',
      dataIndex: 'ip_address',
      width: 130,
      render: (ip: string | undefined) => ip || '-',
    },
    {
      title: '操作',
      width: 70,
      fixed: 'right',
      render: (_, record) => (
        <Button
          type="link"
          size="small"
          icon={<EyeOutlined />}
          onClick={() => handleViewDetail(record)}
        />
      ),
    },
  ]

  return (
    <div style={{ padding: '0 0 24px' }}>
      {/* 页面标题 + 统计 */}
      <Card size="small" style={{ marginBottom: 16 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
          <div>
            <Title level={4} style={{ margin: '0 0 8px' }}>
              <FileSearchOutlined style={{ marginRight: 8 }} />
              操作日志
            </Title>
            <Text type="secondary" style={{ fontSize: 13 }}>
              查看和管理系统中的用户操作记录
            </Text>
          </div>
          <Space>
            <Button icon={<ReloadOutlined />} onClick={() => loadLogs()} loading={loading}>
              刷新
            </Button>
            <Popconfirm
              title="确定要清空操作日志吗？此操作不可恢复"
              onConfirm={handleClear}
              okText="确定"
              cancelText="取消"
              okButtonProps={{ danger: true }}
            >
              <Button danger icon={<DeleteOutlined />} loading={clearing}>
                清空日志
              </Button>
            </Popconfirm>
          </Space>
        </div>

        {/* 统计卡片 */}
        {stats && (
          <Row gutter={16} style={{ marginTop: 16 }}>
            <Col span={6}>
              <Statistic
                title="总记录数"
                value={stats.total_count}
                styles={{ content: { fontSize: 20 } }}
                prefix={<BarChartOutlined />}
              />
            </Col>
            <Col span={6}>
              <Statistic
                title="成功"
                value={stats.success_count}
                styles={{ content: { fontSize: 20, color: '#52C41A' } }}
                prefix={<CheckCircleOutlined />}
              />
            </Col>
            <Col span={6}>
              <Statistic
                title="失败"
                value={stats.failed_count}
                styles={{ content: { fontSize: 20, color: '#FF4D4F' } }}
                prefix={<CloseCircleOutlined />}
              />
            </Col>
            <Col span={6}>
              <Statistic
                title="成功率"
                value={stats.total_count > 0
                  ? ((stats.success_count / stats.total_count) * 100).toFixed(1)
                  : 0}
                suffix="%"
                styles={{ content: { fontSize: 20 } }}
              />
            </Col>
          </Row>
        )}
      </Card>

      {/* 筛选区域 */}
      <Card size="small" style={{ marginBottom: 16 }}>
        <Space wrap size="middle">
          <Space size="small">
            <FilterOutlined style={{ color: '#C9A96E' }} />
            <Text strong style={{ fontSize: 13 }}>筛选：</Text>
          </Space>
          <Input
            placeholder="搜索关键词"
            allowClear
            value={keyword}
            onChange={(e) => setKeyword(e.target.value)}
            onPressEnter={handleFilterChange}
            style={{ width: 180 }}
          />
          <Select
            value={actionType}
            onChange={(v) => { setActionType(v); handleFilterChange() }}
            options={ACTION_TYPE_OPTIONS}
            style={{ width: 120 }}
          />
          <Select
            value={successFilter === undefined ? '' : String(successFilter)}
            onChange={(v) => {
              setSuccessFilter(v === '' ? undefined : v === 'true')
              handleFilterChange()
            }}
            options={[
              { value: '', label: '全部状态' },
              { value: 'true', label: '成功' },
              { value: 'false', label: '失败' },
            ]}
            style={{ width: 110 }}
          />
          <RangePicker
            value={dateRange}
            onChange={(dates) => {
              setDateRange(dates as [dayjs.Dayjs, dayjs.Dayjs] | null)
              handleFilterChange()
            }}
            size="middle"
            placeholder={['开始日期', '结束日期']}
          />
          <Button onClick={handleReset}>重置</Button>
        </Space>
      </Card>

      {/* 日志列表 */}
      <Card size="small">
        <Table
          dataSource={logs}
          columns={columns}
          rowKey="id"
          loading={loading}
          scroll={{ x: 1000 }}
          size="small"
          pagination={{
            current: page,
            pageSize,
            total,
            showTotal: (t) => `共 ${t} 条`,
            showSizeChanger: true,
            showQuickJumper: true,
            pageSizeOptions: ['10', '20', '50', '100'],
            onChange: handlePageChange,
          }}
          locale={{
            emptyText: <Empty description="暂无操作日志" image={Empty.PRESENTED_IMAGE_SIMPLE} />,
          }}
        />
      </Card>

      {/* 详情弹窗 */}
      <Modal
        title="操作日志详情"
        open={detailOpen}
        onCancel={() => { setDetailOpen(false); setCurrentLog(null) }}
        footer={[
          <Button key="close" onClick={() => setDetailOpen(false)}>关闭</Button>,
        ]}
        width={650}
      >
        <Spin spinning={detailLoading}>
          {currentLog && (
            <Descriptions column={2} bordered size="small">
              <Descriptions.Item label="日志 ID">{currentLog.id}</Descriptions.Item>
              <Descriptions.Item label="时间">
                {new Date(currentLog.timestamp).toLocaleString()}
              </Descriptions.Item>
              <Descriptions.Item label="用户名">{currentLog.username}</Descriptions.Item>
              <Descriptions.Item label="用户 ID">{currentLog.user_id}</Descriptions.Item>
              <Descriptions.Item label="操作类型">
                <Tag color="blue">{ACTION_TYPE_LABELS[currentLog.action_type] || currentLog.action_type}</Tag>
              </Descriptions.Item>
              <Descriptions.Item label="状态">
                <Tag
                  icon={currentLog.success ? <CheckCircleOutlined /> : <CloseCircleOutlined />}
                  color={currentLog.success ? 'success' : 'error'}
                >
                  {currentLog.success ? '成功' : '失败'}
                </Tag>
              </Descriptions.Item>
              <Descriptions.Item label="操作描述" span={2}>{currentLog.action}</Descriptions.Item>
              <Descriptions.Item label="IP 地址">{currentLog.ip_address || '-'}</Descriptions.Item>
              <Descriptions.Item label="耗时">
                {currentLog.duration_ms != null ? `${currentLog.duration_ms}ms` : '-'}
              </Descriptions.Item>
              {currentLog.error_message && (
                <Descriptions.Item label="错误信息" span={2}>
                  <Alert
                    type="error"
                    showIcon
                    icon={<WarningOutlined />}
                    title={currentLog.error_message}
                    style={{ margin: 0 }}
                  />
                </Descriptions.Item>
              )}
              {currentLog.details && Object.keys(currentLog.details).length > 0 && (
                <Descriptions.Item label="详细信息" span={2}>
                  <pre style={{
                    background: '#f5f7fa',
                    padding: 12,
                    borderRadius: 4,
                    fontSize: 12,
                    maxHeight: 200,
                    overflow: 'auto',
                    whiteSpace: 'pre-wrap',
                    wordBreak: 'break-all',
                  }}>
                    {JSON.stringify(currentLog.details, null, 2)}
                  </pre>
                </Descriptions.Item>
              )}
            </Descriptions>
          )}
        </Spin>
      </Modal>
    </div>
  )
}
