/**
 * 定时任务列表组件
 * 展示任务表格，支持搜索/筛选、暂停/恢复/触发操作
 */

import { useState, useMemo } from 'react'
import {
  Table, Tag, Button, Space, Input, Select, Typography, Popconfirm,
} from 'antd'
import {
  PauseOutlined, PlayCircleOutlined, ThunderboltOutlined,
  EyeOutlined, EditOutlined, SearchOutlined,
} from '@ant-design/icons'
import type { ColumnsType } from 'antd/es/table'
import type { SchedulerJob } from '@/services/api/scheduler'

const { Text } = Typography

interface JobListProps {
  jobs: SchedulerJob[]
  loading: boolean
  actionLoading: Record<string, boolean>
  onPause?: (jobId: string) => void
  onResume?: (jobId: string) => void
  onTrigger?: (jobId: string) => void
  onViewDetail?: (job: SchedulerJob) => void
  onEdit?: (job: SchedulerJob) => void
}

/** 格式化触发器信息 */
function formatTrigger(trigger: SchedulerJob['trigger']): string {
  if (!trigger) return '-'
  if (trigger.type === 'cron' && trigger.cron_expression) {
    return `Cron: ${trigger.cron_expression}`
  }
  if (trigger.type === 'interval') {
    return `Interval`
  }
  return trigger.type ?? '-'
}

/** 判断任务是否运行中（基于 enabled 字段） */
function isJobRunning(job: SchedulerJob): boolean {
  return job.enabled
}

export default function JobList({
  jobs,
  loading,
  actionLoading,
  onPause,
  onResume,
  onTrigger,
  onViewDetail,
  onEdit,
}: JobListProps) {
  const [keyword, setKeyword] = useState('')
  const [filterStatus, setFilterStatus] = useState<string>('')

  /** 过滤后的任务列表 */
  const filteredJobs = useMemo(() => {
    let result = [...jobs]

    if (keyword.trim()) {
      const kw = keyword.toLowerCase()
      result = result.filter(job =>
        job.name.toLowerCase().includes(kw) ||
        job.id.toLowerCase().includes(kw) ||
        (job.display_name?.toLowerCase().includes(kw) ?? false) ||
        (job.description?.toLowerCase().includes(kw) ?? false)
      )
    }

    if (filterStatus === 'running') {
      result = result.filter(j => isJobRunning(j))
    } else if (filterStatus === 'paused') {
      result = result.filter(j => !isJobRunning(j))
    }

    // 默认排序：运行中优先
    result.sort((a, b) => {
      if (isJobRunning(a) !== isJobRunning(b)) {
        return isJobRunning(a) ? -1 : 1
      }
      return a.name.localeCompare(b.name, 'zh-CN')
    })

    return result
  }, [jobs, keyword, filterStatus])

  const columns: ColumnsType<SchedulerJob> = [
    {
      title: '任务名称',
      dataIndex: 'name',
      width: 200,
      render: (text, record) => (
        <Space>
          <Tag color={isJobRunning(record) ? 'success' : 'warning'}>
            {isJobRunning(record) ? '运行中' : '已暂停'}
          </Tag>
          <Text strong>{text}</Text>
        </Space>
      ),
    },
    {
      title: '显示名称',
      dataIndex: 'display_name',
      width: 140,
      render: (t: string | undefined) => t || <Text type="secondary">-</Text>,
    },
    {
      title: '触发器',
      dataIndex: 'trigger',
      width: 180,
      render: (trigger: SchedulerJob['trigger']) => (
        <Text type="secondary" style={{ fontSize: 12 }}>{formatTrigger(trigger)}</Text>
      ),
    },
    {
      title: '备注',
      dataIndex: 'description',
      width: 200,
      ellipsis: true,
      render: (d: string | undefined) => d || <Text type="secondary">-</Text>,
    },
    {
      title: '下次执行时间',
      dataIndex: 'next_run_time',
      width: 170,
      render: (t: string | undefined) =>
        t ? <Text style={{ fontSize: 12 }}>{new Date(t).toLocaleString()}</Text> : <Text type="warning">已暂停</Text>,
    },
    {
      title: '操作',
      width: 300,
      fixed: 'right',
      render: (_, record) => (
        <Space size={2}>
          {onEdit && (
            <Button size="small" icon={<EditOutlined />} onClick={() => onEdit(record)} />
          )}
          {isJobRunning(record) ? (
            <Button
              size="small"
              icon={<PauseOutlined />}
              onClick={() => onPause?.(record.id)}
              loading={actionLoading[record.id]}
            >
              暂停
            </Button>
          ) : (
            <Button
              size="small"
              icon={<PlayCircleOutlined />}
              onClick={() => onResume?.(record.id)}
              loading={actionLoading[record.id]}
              style={{ color: '#52C41A' }}
            >
              恢复
            </Button>
          )}
          <Popconfirm
            title={`确定要立即执行「${record.name}」吗？`}
            onConfirm={() => onTrigger?.(record.id)}
            okText="确定"
            cancelText="取消"
          >
            <Button
              size="small"
              type="primary"
              icon={<ThunderboltOutlined />}
              loading={actionLoading[record.id]}
            >
              执行
            </Button>
          </Popconfirm>
          {onViewDetail && (
            <Button size="small" icon={<EyeOutlined />} onClick={() => onViewDetail(record)} />
          )}
        </Space>
      ),
    },
  ]

  return (
    <div>
      {/* 搜索和筛选栏 */}
      <Space style={{ marginBottom: 12 }} wrap>
        <Input
          placeholder="搜索任务名称..."
          prefix={<SearchOutlined />}
          value={keyword}
          onChange={(e) => setKeyword(e.target.value)}
          allowClear
          style={{ width: 240 }}
        />
        <Select
          placeholder="状态筛选"
          value={filterStatus}
          onChange={setFilterStatus}
          allowClear
          style={{ width: 140 }}
          options={[
            { value: 'running', label: '运行中' },
            { value: 'paused', label: '已暂停' },
          ]}
        />
        {(keyword || filterStatus) && (
          <Button
            size="small"
            onClick={() => { setKeyword(''); setFilterStatus('') }}
          >
            重置
          </Button>
        )}
      </Space>

      {/* 任务表格 */}
      <Table
        dataSource={filteredJobs}
        columns={columns}
        rowKey="id"
        loading={loading}
        pagination={false}
        size="small"
        scroll={{ x: 1100 }}
        locale={{
          emptyText: filteredJobs.length === 0 && jobs.length > 0
            ? '没有匹配的任务'
            : '暂无定时任务',
        }}
      />
    </div>
  )
}
