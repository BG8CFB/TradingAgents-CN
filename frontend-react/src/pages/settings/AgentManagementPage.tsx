/**
 * 智能体管理页面
 * 功能：查看所有智能体配置（系统+自定义）、编辑参数、启用/禁用、删除自定义智能体
 */

import { useState, useEffect, useCallback } from 'react'
import {
  Card, Button, Space, Typography, Table, Tag, Switch, Modal, Form,
  Input, Select, Popconfirm, message, Spin, Empty, Descriptions, Alert,
} from 'antd'
import {
  ReloadOutlined, PlusOutlined, EditOutlined, DeleteOutlined,
  RobotOutlined, EyeOutlined,
} from '@ant-design/icons'
import type { ColumnsType } from 'antd/es/table'
import { listAgents, saveAgent, deleteAgent, type AgentItem } from '@/services/api/agents'

const { Title, Text } = Typography

/** 阶段中文映射 */
const STAGE_LABELS: Record<string, string> = {
  analysis: '分析阶段',
  research: '研究阶段',
  risk: '风险阶段',
  trading: '交易阶段',
}

/** 阶段颜色 */
const STAGE_COLORS: Record<string, string> = {
  analysis: 'blue',
  research: 'purple',
  risk: 'orange',
  trading: 'gold',
}

export default function AgentManagementPage() {
  const [agents, setAgents] = useState<AgentItem[]>([])
  const [loading, setLoading] = useState(false)
  const [editOpen, setEditOpen] = useState(false)
  const [detailOpen, setDetailOpen] = useState(false)
  const [editingAgent, setEditingAgent] = useState<AgentItem | null>(null)
  const [viewingAgent, setViewingAgent] = useState<AgentItem | null>(null)
  const [saving, setSaving] = useState(false)

  /** 加载智能体列表 */
  const fetchAgents = useCallback(async () => {
    setLoading(true)
    try {
      const res = await listAgents()
      setAgents(Array.isArray(res) ? res : [])
    } catch {
      message.error('加载智能体列表失败')
      setAgents([])
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    fetchAgents()
  }, [fetchAgents])

  /** 打开编辑弹窗 */
  const handleEdit = (agent: AgentItem) => {
    setEditingAgent(agent)
    setEditOpen(true)
  }

  /** 打开新增弹窗 */
  const handleAdd = () => {
    setEditingAgent(null)
    setEditOpen(true)
  }

  /** 查看详情 */
  const handleViewDetail = (agent: AgentItem) => {
    setViewingAgent(agent)
    setDetailOpen(true)
  }

  /** 保存智能体 */
  const handleSave = async (values: Partial<AgentItem>) => {
    setSaving(true)
    try {
      if (editingAgent) {
        // 编辑
        await saveAgent({ ...editingAgent, ...values })
        message.success('智能体配置已更新')
      } else {
        // 新增
        await saveAgent({
          id: `custom_${Date.now()}`,
          name: values.name || '新智能体',
          stage: values.stage || 'analysis',
          type: values.type || 'custom',
          description: values.description || '',
          prompt: values.prompt || '',
          enabled: true,
        })
        message.success('智能体已创建')
      }
      setEditOpen(false)
      await fetchAgents()
    } catch {
      message.error('保存失败')
    } finally {
      setSaving(false)
    }
  }

  /** 删除智能体 */
  const handleDelete = async (agentId: string) => {
    try {
      const res = await deleteAgent(agentId)
      message.success(res.message || '删除成功')
      await fetchAgents()
    } catch {
      message.error('删除失败')
    }
  }

  /** 切换启用状态 */
  const handleToggleEnabled = async (agent: AgentItem, enabled: boolean) => {
    try {
      await saveAgent({ ...agent, enabled })
      message.success(`${enabled ? '启用' : '禁用'}成功`)
      await fetchAgents()
    } catch {
      message.error('操作失败')
    }
  }

  // ========== 表格列定义 ==========
  const columns: ColumnsType<AgentItem> = [
    {
      title: '名称',
      dataIndex: 'name',
      width: 160,
      render: (text, record) => (
        <Space>
          <RobotOutlined style={{ color: '#C9A96E' }} />
          <Text strong>{text}</Text>
          {record.is_system && <Tag color="processing">系统</Tag>}
        </Space>
      ),
    },
    {
      title: '阶段',
      dataIndex: 'stage',
      width: 100,
      render: (stage: string) => (
        <Tag color={STAGE_COLORS[stage] ?? 'default'}>{STAGE_LABELS[stage] || stage}</Tag>
      ),
    },
    {
      title: '类型',
      dataIndex: 'type',
      width: 100,
      render: (t: string) => <Tag>{t}</Tag>,
    },
    {
      title: '描述',
      dataIndex: 'description',
      ellipsis: true,
      render: (desc: string) => desc || <Text type="secondary">-</Text>,
    },
    {
      title: '状态',
      dataIndex: 'enabled',
      width: 80,
      render: (enabled: boolean, record) => (
        <Switch
          size="small"
          checked={enabled}
          onChange={(checked) => handleToggleEnabled(record, checked)}
          checkedChildren="启用"
          unCheckedChildren="禁用"
        />
      ),
    },
    {
      title: '操作',
      width: 180,
      fixed: 'right',
      render: (_, record) => (
        <Space size="small">
          <Button size="small" icon={<EyeOutlined />} onClick={() => handleViewDetail(record)} />
          <Button size="small" icon={<EditOutlined />} onClick={() => handleEdit(record)} />
          {!record.is_system && (
            <Popconfirm
              title={`确定要删除「${record.name}」吗？`}
              onConfirm={() => handleDelete(record.id)}
              okText="确定"
              cancelText="取消"
            >
              <Button size="small" danger icon={<DeleteOutlined />} />
            </Popconfirm>
          )}
        </Space>
      ),
    },
  ]

  return (
    <div style={{ padding: '0 0 24px' }}>
      {/* 页面标题 */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 20 }}>
        <Title level={4} style={{ margin: 0 }}>
          <RobotOutlined style={{ marginRight: 8 }} />
          智能体管理
        </Title>
        <Space>
          <Button icon={<ReloadOutlined />} onClick={fetchAgents} loading={loading}>
            刷新
          </Button>
          <Button type="primary" icon={<PlusOutlined />} onClick={handleAdd}>
            添加智能体
          </Button>
        </Space>
      </div>

      {/* 提示信息 */}
      <Alert
        type="info"
        showIcon
        style={{ marginBottom: 16 }}
        title="智能体说明"
        description={
          <span>
            系统内置了研究阶段（Bull/Bear Researcher + Research Manager）、风险阶段（Risk Manager）和交易阶段（Trader）共 5 个智能体。
            您可以编辑它们的参数或添加自定义智能体。系统智能体不可删除，只能重置为默认配置。
          </span>
        }
      />

      {/* 智能体列表 */}
      <Card>
        <Spin spinning={loading}>
          {agents.length === 0 && !loading ? (
            <Empty description="暂无智能体配置" />
          ) : (
            <Table
              dataSource={agents}
              columns={columns}
              rowKey="id"
              pagination={false}
              size="small"
              scroll={{ x: 900 }}
            />
          )}
        </Spin>
      </Card>

      {/* 编辑/新增对话框 */}
      <Modal
        title={editingAgent ? `编辑智能体：${editingAgent.name}` : '添加智能体'}
        open={editOpen}
        onCancel={() => setEditOpen(false)}
        destroyOnHidden
        footer={null}
        width={600}
      >
        <Form
          layout="vertical"
          initialValues={editingAgent ?? { stage: 'analysis', type: 'custom', enabled: true }}
          onFinish={handleSave}
        >
          {!editingAgent && (
            <Form.Item name="name" label="名称" rules={[{ required: true, message: '请输入名称' }]}>
              <Input placeholder="输入智能体名称" />
            </Form.Item>
          )}
          {editingAgent && (
            <Form.Item label="ID">
              <Input value={editingAgent.id} disabled />
            </Form.Item>
          )}
          <Space style={{ width: '100%' }} wrap>
            <Form.Item name="stage" label="所属阶段" style={{ flex: 1, minWidth: 150 }}
              rules={[{ required: true }]}>
              <Select options={[
                { value: 'analysis', label: '分析阶段' },
                { value: 'research', label: '研究阶段' },
                { value: 'risk', label: '风险阶段' },
                { value: 'trading', label: '交易阶段' },
              ]} />
            </Form.Item>
            <Form.Item name="type" label="类型" style={{ flex: 1, minWidth: 150 }}>
              <Input placeholder="如 market, social, custom" />
            </Form.Item>
          </Space>
          <Form.Item name="description" label="描述">
            <Input.TextArea rows={2} placeholder="智能体的功能描述" />
          </Form.Item>
          <Form.Item name="prompt" label="Prompt 模板">
            <Input.TextArea rows={4} placeholder="智能体的角色定义和指令模板" />
          </Form.Item>
          <Form.Item name="enabled" label="启用" valuePropName="checked">
            <Switch checkedChildren="启用" unCheckedChildren="禁用" />
          </Form.Item>
          <Form.Item style={{ textAlign: 'right', marginBottom: 0 }}>
            <Space>
              <Button onClick={() => setEditOpen(false)}>取消</Button>
              <Button type="primary" htmlType="submit" loading={saving}>保存</Button>
            </Space>
          </Form.Item>
        </Form>
      </Modal>

      {/* 详情对话框 */}
      <Modal
        title={`智能体详情：${viewingAgent?.name ?? ''}`}
        open={detailOpen}
        onCancel={() => setDetailOpen(false)}
        footer={[
          <Button key="close" onClick={() => setDetailOpen(false)}>
            关闭
          </Button>,
          <Button
            key="edit"
            type="primary"
            icon={<EditOutlined />}
            onClick={() => {
              setDetailOpen(false)
              if (viewingAgent) handleEdit(viewingAgent)
            }}
          >
            编辑
          </Button>,
        ]}
        width={650}
      >
        {viewingAgent && (
          <Descriptions column={1} bordered size="small">
            <Descriptions.Item label="ID">{viewingAgent.id}</Descriptions.Item>
            <Descriptions.Item label="名称">{viewingAgent.name}</Descriptions.Item>
            <Descriptions.Item label="阶段">
              <Tag color={STAGE_COLORS[viewingAgent.stage] ?? 'default'}>
                {STAGE_LABELS[viewingAgent.stage] || viewingAgent.stage}
              </Tag>
            </Descriptions.Item>
            <Descriptions.Item label="类型">
              <Tag>{viewingAgent.type}</Tag>
            </Descriptions.Item>
            <Descriptions.Item label="是否系统">
              {viewingAgent.is_system ? <Tag color="processing">是</Tag> : <Tag>否</Tag>}
            </Descriptions.Item>
            <Descriptions.Item label="启用状态">
              <Tag color={viewingAgent.enabled ? 'success' : 'default'}>
                {viewingAgent.enabled ? '已启用' : '已禁用'}
              </Tag>
            </Descriptions.Item>
            <Descriptions.Item label="描述">
              {viewingAgent.description || '-'}
            </Descriptions.Item>
            <Descriptions.Item label="Prompt">
              {viewingAgent.prompt ? (
                <pre style={{
                  margin: 0, padding: 8, background: '#f5f5f5', borderRadius: 4,
                  fontSize: 12, whiteSpace: 'pre-wrap', maxHeight: 200, overflow: 'auto',
                }}>
                  {viewingAgent.prompt}
                </pre>
              ) : '-'}
            </Descriptions.Item>
          </Descriptions>
        )}
      </Modal>
    </div>
  )
}
