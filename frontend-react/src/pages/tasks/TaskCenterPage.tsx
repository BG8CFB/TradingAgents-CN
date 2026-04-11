import { useState } from 'react'
import {
  Card,
  Table,
  Typography,
  Space,
  Button,
  Tag,
  Select,
  message,
  Popconfirm,
  Tooltip,
  Empty,
} from 'antd'
import {
  ReloadOutlined,
  DeleteOutlined,
  StopOutlined,
  ExclamationCircleOutlined,
} from '@ant-design/icons'
import { useTaskList } from '@/features/analysis/hooks/useTaskList'
import TaskStatusBadge from '@/features/analysis/components/TaskStatusBadge'
import AnalysisProgressBar from '@/features/analysis/components/AnalysisProgressBar'
import type { AnalysisTask } from '@/types/analysis.types'

const { Title, Text } = Typography

const statusOptions = [
  { value: '', label: '全部状态' },
  { value: 'pending', label: '待处理' },
  { value: 'processing', label: '进行中' },
  { value: 'completed', label: '已完成' },
  { value: 'failed', label: '失败' },
  { value: 'cancelled', label: '已取消' },
]

export default function TaskCenterPage() {
  const [pageSize] = useState(20)
  const {
    tasks,
    total,
    loading,
    error,
    hasMore,
    statusFilter,
    setStatusFilter,
    refresh,
    loadMore,
    cancelTask,
    deleteTask,
    markTaskFailed,
  } = useTaskList({ pageSize, autoRefresh: true, refreshInterval: 10000 })

  const handleCancel = async (taskId: string) => {
    const ok = await cancelTask(taskId)
    if (ok) message.success('任务已取消')
    else message.error('取消任务失败')
  }

  const handleDelete = async (taskId: string) => {
    const ok = await deleteTask(taskId)
    if (ok) message.success('任务已删除')
    else message.error('删除任务失败')
  }

  const handleMarkFailed = async (taskId: string) => {
    const ok = await markTaskFailed(taskId)
    if (ok) message.success('任务已标记为失败')
    else message.error('标记失败')
  }

  const columns = [
    {
      title: '股票代码',
      dataIndex: 'symbol',
      key: 'symbol',
      render: (_: unknown, record: AnalysisTask) => (
        <Text strong style={{ color: 'var(--text-primary)' }}>
          {record.symbol || record.stock_code || '-'}
        </Text>
      ),
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      render: (status: string) => <TaskStatusBadge status={status} />,
    },
    {
      title: '进度',
      dataIndex: 'progress',
      key: 'progress',
      width: 180,
      render: (progress: number, record: AnalysisTask) =>
        record.status === 'processing' || record.status === 'pending' ? (
          <AnalysisProgressBar progress={progress} size="small" showInfo={false} />
        ) : (
          <Text style={{ color: 'var(--text-secondary)' }}>{progress}%</Text>
        ),
    },
    {
      title: '创建时间',
      dataIndex: 'created_at',
      key: 'created_at',
      render: (v: string) => (
        <Text style={{ color: 'var(--text-secondary)', fontSize: 12 }}>
          {v ? new Date(v).toLocaleString() : '-'}
        </Text>
      ),
    },
    {
      title: '操作',
      key: 'action',
      width: 180,
      render: (_: unknown, record: AnalysisTask) => {
        const canCancel = record.status === 'pending' || record.status === 'processing'
        const canMarkFailed = record.status === 'pending' || record.status === 'processing'

        return (
          <Space size="small">
            {canCancel && (
              <Popconfirm
                title="确认取消该任务？"
                onConfirm={() => handleCancel(record.task_id)}
              >
                <Tooltip title="取消">
                  <Button type="text" danger size="small" icon={<StopOutlined />} />
                </Tooltip>
              </Popconfirm>
            )}
            {canMarkFailed && (
              <Popconfirm
                title="确认标记为失败？"
                onConfirm={() => handleMarkFailed(record.task_id)}
              >
                <Tooltip title="标记失败">
                  <Button
                    type="text"
                    size="small"
                    icon={<ExclamationCircleOutlined style={{ color: 'var(--accent-warning)' }} />}
                  />
                </Tooltip>
              </Popconfirm>
            )}
            <Popconfirm
              title="确认删除该任务？"
              onConfirm={() => handleDelete(record.task_id)}
            >
              <Tooltip title="删除">
                <Button type="text" danger size="small" icon={<DeleteOutlined />} />
              </Tooltip>
            </Popconfirm>
          </Space>
        )
      },
    },
  ]

  return (
    <div style={{ color: 'var(--text-primary)' }}>
      <Title level={3} style={{ color: 'var(--text-primary)', marginBottom: 24 }}>
        任务中心
      </Title>

      <Card
        style={{ background: 'var(--bg-card)', border: 'none' }}
        styles={{ header: { borderBottom: '1px solid rgba(255,255,255,0.06)' } }}
        title={
          <Space>
            <span style={{ color: 'var(--text-primary)' }}>分析任务</span>
            <Tag color="default">共 {total} 个</Tag>
          </Space>
        }
        extra={
          <Space>
            <Select
              value={statusFilter || ''}
              onChange={(v) => setStatusFilter(v || undefined)}
              options={statusOptions}
              style={{ width: 140 }}
            />
            <Button icon={<ReloadOutlined />} onClick={refresh} loading={loading}>
              刷新
            </Button>
          </Space>
        }
      >
        {error && (
          <div style={{ marginBottom: 16 }}>
            <Text type="danger">{error}</Text>
          </div>
        )}

        <Table
          dataSource={tasks}
          columns={columns}
          rowKey="task_id"
          loading={loading && tasks.length === 0}
          pagination={false}
          locale={{
            emptyText: <Empty description="暂无任务" image={Empty.PRESENTED_IMAGE_SIMPLE} />,
          }}
          scroll={{ x: 'max-content' }}
        />

        {hasMore && (
          <div style={{ textAlign: 'center', marginTop: 16 }}>
            <Button onClick={loadMore} loading={loading}>
              加载更多
            </Button>
          </div>
        )}
      </Card>
    </div>
  )
}
