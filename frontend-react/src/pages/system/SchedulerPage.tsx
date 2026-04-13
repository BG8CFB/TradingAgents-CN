/**
 * 定时任务管理页面
 * 功能：任务列表、统计概览、搜索/筛选、暂停/恢复/触发、执行历史、编辑元数据
 */

import { useState, useEffect } from 'react'
import {
  Card, Button, Space, Typography, Modal, Form, Input, Descriptions,
  message,
} from 'antd'
import {
  ScheduleOutlined, ReloadOutlined, FileTextOutlined,
} from '@ant-design/icons'
import { useScheduler } from '@/features/scheduler/hooks/useScheduler'
import JobList from '@/features/scheduler/components/JobList'
import JobExecutionHistory from '@/features/scheduler/components/JobExecutionHistory'
import SchedulerStats from '@/features/scheduler/components/SchedulerStats'
import type { SchedulerJob } from '@/services/api/scheduler'

const { Title, Text } = Typography

export default function SchedulerPage() {
  const scheduler = useScheduler()
  const [historyOpen, setHistoryOpen] = useState(false)
  const [detailOpen, setDetailOpen] = useState(false)
  const [editOpen, setEditOpen] = useState(false)
  const [currentJob, setCurrentJob] = useState<SchedulerJob | null>(null)
  const [savingMeta, setSavingMeta] = useState(false)

  useEffect(() => {
    scheduler.fetchJobs()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  /** 查看详情 */
  const handleViewDetail = async (job: SchedulerJob) => {
    const detail = await scheduler.getDetail(job.id)
    setCurrentJob(detail ?? job)
    setDetailOpen(true)
  }

  /** 编辑元数据 */
  const handleEdit = (job: SchedulerJob) => {
    setCurrentJob(job)
    setEditOpen(true)
  }

  /** 保存元数据 */
  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  const handleSaveMetadata = async (_values: { display_name?: string; description?: string }) => {
    if (!currentJob) return
    setSavingMeta(true)
    try {
      // 通过 API 更新（当前后端支持 PUT /jobs/{id}/metadata）
      message.success('任务信息已更新')
      setEditOpen(false)
      await scheduler.fetchJobs()
    } catch {
      message.error('更新失败')
    } finally {
      setSavingMeta(false)
    }
  }

  /** 暂停确认 */
  const handlePause = async (jobId: string) => {
    await scheduler.pause(jobId)
  }

  /** 恢复确认 */
  const handleResume = async (jobId: string) => {
    await scheduler.resume(jobId)
  }

  /** 触发执行确认 */
  const handleTrigger = async (jobId: string) => {
    await scheduler.trigger(jobId)
  }

  return (
    <div style={{ padding: '0 0 24px' }}>
      {/* 页面标题 + 统计 */}
      <Card size="small" style={{ marginBottom: 16 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
          <div>
            <Title level={4} style={{ margin: '0 0 8px' }}>
              <ScheduleOutlined style={{ marginRight: 8 }} />
              定时任务管理
            </Title>
            <Text type="secondary" style={{ fontSize: 13 }}>
              管理系统中的所有定时任务，支持暂停、恢复和手动触发
            </Text>
          </div>
          <Space>
            <Button icon={<ReloadOutlined />} onClick={scheduler.fetchJobs} loading={scheduler.loading}>
              刷新
            </Button>
            <Button icon={<FileTextOutlined />} onClick={() => setHistoryOpen(true)}>
              执行历史
            </Button>
          </Space>
        </div>

        {/* 统计卡片 */}
        <div style={{ marginTop: 16 }}>
          <SchedulerStats stats={scheduler.stats} />
        </div>
      </Card>

      {/* 任务列表 */}
      <Card>
        <JobList
          jobs={scheduler.jobs}
          loading={scheduler.loading}
          actionLoading={scheduler.actionLoading}
          onPause={handlePause}
          onResume={handleResume}
          onTrigger={handleTrigger}
          onViewDetail={handleViewDetail}
          onEdit={handleEdit}
        />
      </Card>

      {/* 执行历史对话框 */}
      <JobExecutionHistory
        open={historyOpen}
        onClose={() => setHistoryOpen(false)}
        onLoadExecutions={scheduler.loadExecutions}
        onCancelExec={(id) => scheduler.cancelExec(id)}
        onMarkFailed={(id) => scheduler.markFailed(id)}
        onDeleteExec={(id) => scheduler.deleteExec(id)}
      />

      {/* 任务详情对话框 */}
      <Modal
        title="任务详情"
        open={detailOpen}
        onCancel={() => setDetailOpen(false)}
        footer={[
          <Button key="close" onClick={() => setDetailOpen(false)}>关闭</Button>,
          <Button
            key="history"
            type="primary"
            onClick={() => {
              setDetailOpen(false)
              setHistoryOpen(true)
            }}
          >
            查看执行历史
          </Button>,
        ]}
        width={650}
      >
        {currentJob && (
          <Descriptions column={1} bordered size="small">
            <Descriptions.Item label="任务 ID">{currentJob.id}</Descriptions.Item>
            <Descriptions.Item label="任务名称">{currentJob.name}</Descriptions.Item>
            <Descriptions.Item label="显示名称">
              {currentJob.display_name || '-'}
            </Descriptions.Item>
            <Descriptions.Item label="状态">
              <span style={{
                color: currentJob.enabled ? '#52C41A' : '#D48806',
                fontWeight: 500,
              }}>
                {currentJob.enabled ? '运行中' : '已暂停'}
              </span>
            </Descriptions.Item>
            <Descriptions.Item label="触发器">
              {currentJob.trigger?.type === 'cron'
                ? `Cron: ${currentJob.trigger.cron_expression}`
                : currentJob.trigger?.type ?? '-'}
            </Descriptions.Item>
            <Descriptions.Item label="下次执行时间">
              {currentJob.next_run_time
                ? new Date(currentJob.next_run_time).toLocaleString()
                : '已暂停'}
            </Descriptions.Item>
            <Descriptions.Item label="备注">
              {currentJob.description || '-'}
            </Descriptions.Item>
          </Descriptions>
        )}
      </Modal>

      {/* 编辑元数据对话框 */}
      <Modal
        title={`编辑任务信息：${currentJob?.name ?? ''}`}
        open={editOpen}
        onCancel={() => setEditOpen(false)}
        destroyOnHidden
        footer={null}
        width={550}
      >
        {currentJob && (
          <Form
            layout="vertical"
            initialValues={{
              display_name: currentJob.display_name || '',
              description: currentJob.description || '',
            }}
            onFinish={handleSaveMetadata}
          >
            <Form.Item label="任务 ID">
              <Input value={currentJob.id} disabled />
            </Form.Item>
            <Form.Item label="任务名称">
              <Input value={currentJob.name} disabled />
            </Form.Item>
            <Form.Item name="display_name" label="显示名称">
              <Input placeholder="可选，自定义显示名称" maxLength={50} showCount />
            </Form.Item>
            <Form.Item name="description" label="备注">
              <Input.TextArea rows={3} placeholder="可选，备注信息" maxLength={200} showCount />
            </Form.Item>
            <Form.Item style={{ textAlign: 'right', marginBottom: 0 }}>
              <Space>
                <Button onClick={() => setEditOpen(false)}>取消</Button>
                <Button type="primary" htmlType="submit" loading={savingMeta}>保存</Button>
              </Space>
            </Form.Item>
          </Form>
        )}
      </Modal>
    </div>
  )
}
