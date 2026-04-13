/**
 * 市场分类管理器
 * CRUD 操作 + 与数据源的关联展示
 */

import { useState, useCallback, useEffect, useRef } from 'react'
import {
  Table, Button, Modal, Form, Input, InputNumber, Switch, Space, message, Popconfirm, Typography, Tag,
} from 'antd'
import {
  PlusOutlined, EditOutlined, DeleteOutlined, ReloadOutlined,
} from '@ant-design/icons'
import type { ColumnsType } from 'antd/es/table'
import type { MarketCategory, MarketCategoryRequest, DataSourceGrouping, DataSourceConfig } from '@/types/config.types'
import {
  getMarketCategories, addMarketCategory, updateMarketCategory, deleteMarketCategory,
  getDataSourceGroupings, getDataSourceConfigs,
} from '@/services/api/config'

const { Text } = Typography

interface MarketCategoryManagerProps {
  onRefresh?: () => void
}

export default function MarketCategoryManager({ onRefresh }: MarketCategoryManagerProps) {
  const [categories, setCategories] = useState<MarketCategory[]>([])
  const [groupings, setGroupings] = useState<DataSourceGrouping[]>([])
  const [dataSources, setDataSources] = useState<DataSourceConfig[]>([])
  const [loading, setLoading] = useState(false)

  // 弹窗状态
  const [modalOpen, setModalOpen] = useState(false)
  const [editingCategory, setEditingCategory] = useState<MarketCategory | null>(null)
  const [form] = Form.useForm<MarketCategoryRequest>()
  const [saving, setSaving] = useState(false)

  const loadData = useCallback(async () => {
    setLoading(true)
    try {
      const [catRes, grpRes, dsRes] = await Promise.all([
        getMarketCategories(),
        getDataSourceGroupings(),
        getDataSourceConfigs(),
      ])
      setCategories(catRes.data ?? [])
      setGroupings(grpRes.data ?? [])
      setDataSources(dsRes.data ?? [])
    } catch {
      // 静默
    } finally {
      setLoading(false)
    }
  }, [])

  const initializedRef = useRef(false)
  useEffect(() => {
    if (initializedRef.current) return
    initializedRef.current = true
    loadData()
  }, [loadData])

  const handleAdd = () => {
    setEditingCategory(null)
    form.resetFields()
    form.setFieldsValue({ enabled: true, sort_order: 1 })
    setModalOpen(true)
  }

  const handleEdit = (record: MarketCategory) => {
    setEditingCategory(record)
    form.setFieldsValue(record)
    setModalOpen(true)
  }

  const handleSave = async () => {
    try {
      const values = await form.validateFields()
      setSaving(true)
      if (editingCategory) {
        await updateMarketCategory(editingCategory.id, values as unknown as Record<string, unknown>)
        message.success('分类更新成功')
      } else {
        await addMarketCategory(values as MarketCategoryRequest)
        message.success('分类添加成功')
      }
      setModalOpen(false)
      loadData()
      onRefresh?.()
    } catch (error) {
      if (!(error as { errorFields?: unknown }).errorFields) {
        message.error('保存失败')
      }
    } finally {
      setSaving(false)
    }
  }

  const handleDelete = async (id: string) => {
    try {
      await deleteMarketCategory(id)
      message.success('分类已删除')
      loadData()
      onRefresh?.()
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      message.error(msg || '删除失败')
    }
  }

  /** 获取某分类下的数据源列表 */
  const getCategoryDataSources = (categoryId: string): DataSourceConfig[] => {
    const names = groupings
      .filter(g => g.market_category_id === categoryId && g.enabled)
      .sort((a, b) => a.priority - b.priority)
      .map(g => g.data_source_name)
    return dataSources.filter(ds => names.includes(ds.name))
  }

  const columns: ColumnsType<MarketCategory> = [
    { title: 'ID', dataIndex: 'id', width: 120, render: t => <Text code>{t}</Text> },
    { title: '名称', dataIndex: 'name', width: 140 },
    { title: '显示名', dataIndex: 'display_name', width: 140 },
    {
      title: '关联数据源',
      dataIndex: 'id',
      width: 240,
      render: (_id, record) => {
        const sources = getCategoryDataSources(record.id)
        return (
          <span>
            {sources.length > 0 ? sources.map(ds => (
              <Tag key={ds.name} color={ds.enabled ? 'processing' : 'default'}>
                {ds.display_name || ds.name}
              </Tag>
            )) : <Text type="secondary" style={{ fontSize: 12 }}>无关联</Text>}
          </span>
        )
      },
    },
    {
      title: '排序',
      dataIndex: 'sort_order',
      width: 70,
      sorter: (a, b) => (a.sort_order ?? 0) - (b.sort_order ?? 0),
    },
    {
      title: '状态',
      dataIndex: 'enabled',
      width: 80,
      render: v => v ? <Tag color="success">启用</Tag> : <Tag color="default">禁用</Tag>,
    },
    {
      title: '操作',
      width: 120,
      render: (_, record) => (
        <Space size="small">
          <Button type="link" size="small" icon={<EditOutlined />} onClick={() => handleEdit(record)} />
          <Popconfirm title="确定删除此分类？" onConfirm={() => handleDelete(record.id)}>
            <Button type="link" size="small" danger icon={<DeleteOutlined />} />
          </Popconfirm>
        </Space>
      ),
    },
  ]

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
        <Text strong style={{ fontSize: 15 }}>市场分类管理</Text>
        <Space>
          <Button icon={<ReloadOutlined />} onClick={loadData} loading={loading}>刷新</Button>
          <Button type="primary" icon={<PlusOutlined />} onClick={handleAdd}>新增分类</Button>
        </Space>
      </div>

      <Table
        dataSource={categories}
        columns={columns}
        rowKey="id"
        loading={loading}
        pagination={false}
        size="small"
        locale={{ emptyText: '暂无市场分类，点击"新增分类"创建' }}
      />

      <Modal
        title={editingCategory ? `编辑分类：${editingCategory.display_name}` : '新增市场分类'}
        open={modalOpen}
        onCancel={() => setModalOpen(false)}
        onOk={handleSave}
        confirmLoading={saving}
        destroyOnHidden
      >
        <Form form={form} layout="vertical">
          <Form.Item name="id" label="ID" rules={[{ required: true, message: '请输入唯一 ID' }]}>
            <Input placeholder="如 china_a_share、us_stock" disabled={!!editingCategory} />
          </Form.Item>
          <Form.Item name="name" label="内部名称" rules={[{ required: true }]}>
            <Input placeholder="如 A股、美股" />
          </Form.Item>
          <Form.Item name="display_name" label="显示名称" rules={[{ required: true }]}>
            <Input placeholder="如 A 股市场、美国股市" />
          </Form.Item>
          <Form.Item name="description" label="描述">
            <Input.TextArea rows={2} />
          </Form.Item>
          <Space>
            <Form.Item name="sort_order" label="排序" initialValue={1}>
              <InputNumber min={1} max={999} />
            </Form.Item>
            <Form.Item name="enabled" label="启用" valuePropName="checked" initialValue={true}>
              <Switch checkedChildren="启用" unCheckedChildren="禁用" />
            </Form.Item>
          </Space>
        </Form>
      </Modal>
    </div>
  )
}
