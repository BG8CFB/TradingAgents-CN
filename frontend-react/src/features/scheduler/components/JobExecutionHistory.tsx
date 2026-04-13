/**
 * 任务执行历史对话框组件
 * 展示手动操作历史和自动执行监控（双 Tab）
 */

import { useState, useEffect, useRef } from 'react'
import {
  Modal, Table, Tabs, Tag, Button, Space, Typography, Spin, Popconfirm,
  Select, Pagination, Progress, Alert,
} from 'antd'
import {
  CloseCircleOutlined, StopOutlined, DeleteOutlined,
  EyeOutlined, ReloadOutlined,
} from '@ant-design/icons'
import type { ColumnsType } from 'antd/es/table'
import type { JobExecution } from '@/services/api/scheduler'

const { Text } = Typography

interface JobExecutionHistoryProps {
  open: boolean
  onClose: () => void
  /** 加载执行记录 */
  onLoadExecutions: (params?: {
    job_id?: string; status?: string; is_manual?: boolean | null; limit?: number; offset?: number
  }) => Promise<{ items: JobExecution[]; total: number; limit: number; offset: number }>
  /** 取消执行 */
  onCancelExec?: (executionId: string) => void
  /** 标记失败 */
  onMarkFailed?: (executionId: string, reason?: string) => void
  /** 删除记录 */
  onDeleteExec?: (executionId: string) => void
}

/** 格式化执行状态 */
function formatStatus(status: string): { label: string; color: string } {
  const map: Record<string, { label: string; color: string }> = {
    running:   { label: '执行中', color: 'processing' },
    success:   { label: '成功',   color: 'success' },
    failed:    { label: '失败',   color: 'error' },
    missed:    { label: '错过',   color: 'warning' },
  }
  return map[status] ?? { label: status, color: 'default' }
}

/** 计算运行时长 */
function calcDuration(startedAt: string, finishedAt?: string): string {
  try {
    const start = new Date(startedAt).getTime()
    const end = finishedAt ? new Date(finishedAt).getTime() : Date.now()
    const seconds = Math.floor((end - start) / 1000)
    if (seconds < 60) return `${seconds}秒`
    const mins = Math.floor(seconds / 60)
    return `${mins}分${seconds % 60}秒`
  } catch {
    return '-'
  }
}

export default function JobExecutionHistory({
  open,
  onClose,
  onLoadExecutions,
  onCancelExec,
  onMarkFailed,
  onDeleteExec,
}: JobExecutionHistoryProps) {
  const [activeTab, setActiveTab] = useState('manual')
  const [executions, setExecutions] = useState<JobExecution[]>([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(false)
  const [page, setPage] = useState(1)
  const [pageSize] = useState(20)
  const [statusFilter, setStatusFilter] = useState<string>('')
  const [detailOpen, setDetailOpen] = useState(false)
  const [currentExecution, setCurrentExecution] = useState<JobExecution | null>(null)

  // 自动刷新定时器
  const autoRefreshTimer = useRef<ReturnType<typeof setInterval> | null>(null)

  /** 加载数据 */
  const loadData = async () => {
    setLoading(true)
    try {
      const res = await onLoadExecutions({
        is_manual: activeTab === 'manual',
        status: statusFilter || undefined,
        limit: pageSize,
        offset: (page - 1) * pageSize,
      })
      setExecutions(res.items)
      setTotal(res.total)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    if (open) {
      loadData()
      // 执行中的任务每5秒自动刷新
      autoRefreshTimer.current = setInterval(loadData, 5000)
    }
    return () => {
      if (autoRefreshTimer.current) clearInterval(autoRefreshTimer.current)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, activeTab, page, statusFilter])

  /** 查看详情 */
  const handleViewDetail = (record: JobExecution) => {
    setCurrentExecution(record)
    setDetailOpen(true)
  }

  // ========== 表格列定义 ==========
  const columns: ColumnsType<JobExecution> = [
    {
      title: '任务名称',
      dataIndex: 'job_id',
      width: 180,
      ellipsis: true,
    },
    {
      title: '状态',
      dataIndex: 'status',
      width: 90,
      render: (s: string) => {
        const { label, color } = formatStatus(s)
        return <Tag color={label === '执行中' ? 'processing' : color}>{label}</Tag>
      },
    },
    {
      title: '进度',
      width: 150,
      render: (_, record) => {
        // 尝试从 result 中解析进度信息
        let progress: number | undefined
        let progressMsg = ''
        try {
          if (record.result) {
            const parsed = JSON.parse(record.result)
            progress = parsed.progress
            progressMsg = parsed.progress_message || parsed.current_item || ''
          }
        } catch {
          // ignore parse error
        }
        if (record.status === 'running' && progress !== undefined) {
          return (
            <div>
              <Progress percent={progress} size="small" />
              {progressMsg && (
                <Text type="secondary" style={{ fontSize: 11 }}>{progressMsg}</Text>
              )}
            </div>
          )
        }
        return record.status === 'running' ? <Text type="secondary">运行中...</Text> : <Text type="secondary">-</Text>
      },
    },
    {
      title: '执行时长',
      width: 120,
      render: (_, record) => (
        <Text style={{ fontSize: 12 }}>{calcDuration(record.started_at, record.finished_at)}</Text>
      ),
    },
    {
      title: '开始时间',
      dataIndex: 'started_at',
      width: 160,
      render: (t: string) => new Date(t).toLocaleString(),
    },
    {
      title: '操作',
      width: 200,
      fixed: 'right',
      render: (_, record) => (
        <Space size={2}>
          {(record.error || record.status === 'running') && (
            <Button size="small" icon={<EyeOutlined />} onClick={() => handleViewDetail(record)} />
          )}
          {record.status === 'running' && onCancelExec && (
            <Popconfirm title="确定要终止此执行？" onConfirm={() => onCancelExec(record.id)}>
              <Button size="small" danger icon={<StopOutlined />}>终止</Button>
            </Popconfirm>
          )}
          {record.status === 'running' && onMarkFailed && (
            <Button size="small" icon={<CloseCircleOutlined />} onClick={() => onMarkFailed(record.id)}>
              标记失败
            </Button>
          )}
          {record.status !== 'running' && onDeleteExec && (
            <Popconfirm title="确定删除此记录？" onConfirm={() => onDeleteExec(record.id)}>
              <Button size="small" danger icon={<DeleteOutlined />} />
            </Popconfirm>
          )}
        </Space>
      ),
    },
  ]

  return (
    <>
      <Modal
        title="执行历史"
        open={open}
        onCancel={onClose}
        width={1100}
        footer={<Button onClick={onClose}>关闭</Button>}
        destroyOnHidden
      >
        <Tabs
          activeKey={activeTab}
          onChange={(key) => { setActiveTab(key); setPage(1) }}
          items={[
            { key: 'manual', label: '手动操作历史' },
            { key: 'auto', label: '自动执行监控' },
          ]}
        />

        {/* 筛选栏 */}
        <Space style={{ marginBottom: 12 }} wrap>
          <Select
            placeholder="状态筛选"
            value={statusFilter || undefined}
            onChange={(v) => { setStatusFilter(v || ''); setPage(1) }}
            allowClear
            style={{ width: 140 }}
            options={[
              { value: 'running', label: '执行中' },
              { value: 'success', label: '成功' },
              { value: 'failed', label: '失败' },
              { value: 'missed', label: '错过' },
            ]}
          />
          <Button size="small" icon={<ReloadOutlined />} onClick={loadData} loading={loading}>
            刷新
          </Button>
        </Space>

        {/* 表格 */}
        <Spin spinning={loading}>
          <Table
            dataSource={executions}
            columns={columns}
            rowKey="id"
            pagination={false}
            size="small"
            scroll={{ x: 1000 }}
            style={{ maxHeight: 450 }}
          />

          {/* 分页 */}
          {total > pageSize && (
            <div style={{ textAlign: 'right', marginTop: 12 }}>
              <Pagination
                current={page}
                total={total}
                pageSize={pageSize}
                onChange={(p) => setPage(p)}
                showTotal={(t) => `共 ${t} 条`}
                size="small"
              />
            </div>
          )}
        </Spin>
      </Modal>

      {/* 执行详情对话框 */}
      <Modal
        title="执行详情"
        open={detailOpen}
        onCancel={() => setDetailOpen(false)}
        footer={<Button onClick={() => setDetailOpen(false)}>关闭</Button>}
        width={700}
      >
        {currentExecution && (
          <div>
            <Alert
              type={
                currentExecution.status === 'success' ? 'success' :
                currentExecution.status === 'failed' ? 'error' :
                currentExecution.status === 'running' ? 'info' : 'warning'
              }
              showIcon
              title={formatStatus(currentExecution.status).label}
              style={{ marginBottom: 16 }}
            />

            <table style={{ width: '100%', borderCollapse: 'collapse' }}>
              <tbody>
                {[
                  ['任务 ID', currentExecution.job_id],
                  ['状态', formatStatus(currentExecution.status).label],
                  ['开始时间', new Date(currentExecution.started_at).toLocaleString()],
                  ['结束时间', currentExecution.finished_at ? new Date(currentExecution.finished_at).toLocaleString() : '-'],
                  ['执行时长', calcDuration(currentExecution.started_at, currentExecution.finished_at)],
                  ['是否手动触发', currentExecution.is_manual ? '是' : '否'],
                ].map(([label, val]) => (
                  <tr key={String(label)}>
                    <td style={{ padding: '6px 12px', background: '#fafafa', fontWeight: 500, width: 120 }}>{label}</td>
                    <td style={{ padding: '6px 12px' }}>{String(val)}</td>
                  </tr>
                ))}
              </tbody>
            </table>

            {currentExecution.result && (
              <div style={{ marginTop: 16 }}>
                <Text strong>结果：</Text>
                <pre style={{
                  padding: 8, background: '#f5f5f5', borderRadius: 4,
                  fontSize: 12, maxHeight: 200, overflow: 'auto',
                }}>
                  {currentExecution.result}
                </pre>
              </div>
            )}

            {currentExecution.error && (
              <Alert
                type="error"
                showIcon
                style={{ marginTop: 12 }}
                title="错误信息"
                description={<pre style={{ margin: 0, fontSize: 12 }}>{currentExecution.error}</pre>}
              />
            )}
          </div>
        )}
      </Modal>
    </>
  )
}
