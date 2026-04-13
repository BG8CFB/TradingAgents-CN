/**
 * 模型目录管理器
 * 按供应商展示/编辑模型列表，支持从 API 拉取、手动编辑、初始化默认目录
 */

import { useState, useCallback, useEffect, useRef } from 'react'
import {
  Card, Table, Button, Modal, Input, Space, Tag, message, Popconfirm, Typography, Empty, Tabs,
} from 'antd'
import {
  PlusOutlined, DeleteOutlined, CloudDownloadOutlined, ReloadOutlined, EditOutlined,
} from '@ant-design/icons'
import type { ColumnsType } from 'antd/es/table'
import type { ModelCatalog, ModelInfo, LLMProviderResponse } from '@/types/config.types'
import {
  getModelCatalog, saveModelCatalog,
  deleteModelCatalog, initModelCatalog, fetchProviderModels,
} from '@/services/api/config'

const { Text, Title } = Typography

interface ModelCatalogManagerProps {
  providers: LLMProviderResponse[]
  onRefresh?: () => void
}

export default function ModelCatalogManager({ providers = [], onRefresh }: ModelCatalogManagerProps) {
  const [catalogs, setCatalogs] = useState<ModelCatalog[]>([])
  const safeCatalogs = catalogs ?? []
  const [loading, setLoading] = useState(false)
  const [editModalOpen, setEditModalOpen] = useState(false)
  const [editingProvider, setEditingProvider] = useState<string | null>(null)
  const [editingModels, setEditingModels] = useState<ModelInfo[]>([])
  const [fetchingModels, setFetchingModels] = useState<string | null>(null)

  const loadCatalogs = useCallback(async () => {
    setLoading(true)
    try {
      const res = await getModelCatalog()
      setCatalogs(res.data ?? [])
    } catch {
      // 静默处理
    } finally {
      setLoading(false)
    }
  }, [])

  // 首次加载（ guarded 防止 StrictMode 双调）
  const initializedRef = useRef(false)
  useEffect(() => {
    if (initializedRef.current) return
    initializedRef.current = true
    loadCatalogs()
  }, [loadCatalogs])

  const handleInitDefault = async () => {
    try {
      const res = await initModelCatalog()
      message[res.data.success ? 'success' : 'error'](res.data.message)
      loadCatalogs()
      onRefresh?.()
    } catch {
      message.error('初始化失败')
    }
  }

  const handleFetchModels = async (providerId: string, providerName: string) => {
    setFetchingModels(providerId)
    try {
      const res = await fetchProviderModels(providerId)
      if (res.data.models?.length) {
        message.success(`从 ${providerName} 拉取到 ${res.data.models.length} 个模型`)
      } else {
        message.info(`未从 ${providerName} 获取到模型列表`)
      }
      loadCatalogs()
    } catch {
      message.error('拉取模型失败')
    } finally {
      setFetchingModels(null)
    }
  }

  const handleEditCatalog = (provider: string) => {
    const catalog = catalogs.find(c => c.provider === provider)
    setEditingProvider(provider)
    setEditingModels(catalog?.models ?? [])
    setEditModalOpen(true)
  }

  const handleSaveCatalog = async () => {
    if (!editingProvider) return
    const provider = providers.find(p => p.name === editingProvider)
    try {
      await saveModelCatalog({
        provider: editingProvider,
        provider_name: provider?.display_name || editingProvider,
        models: editingModels,
      })
      message.success('模型目录保存成功')
      setEditModalOpen(false)
      loadCatalogs()
      onRefresh?.()
    } catch {
      message.error('保存失败')
    }
  }

  const handleDeleteCatalog = async (provider: string) => {
    try {
      await deleteModelCatalog(provider)
      message.success('模型目录已删除')
      loadCatalogs()
      onRefresh?.()
    } catch {
      message.error('删除失败')
    }
  }

  /** 添加空模型行 */
  const addModelRow = () => {
    setEditingModels(prev => [...prev, {
      name: '',
      display_name: '',
      description: '',
      context_length: undefined,
      max_tokens: undefined,
      input_price_per_1k: undefined,
      output_price_per_1k: undefined,
      currency: 'CNY',
      is_deprecated: false,
      capabilities: [],
    }])
  }

  /** 更新模型行数据 */
  const updateModelRow = (index: number, field: keyof ModelInfo, value: unknown) => {
    setEditingModels(prev => prev.map((m, i) => i === index ? { ...m, [field]: value } : m))
  }

  /** 删除模型行 */
  const removeModelRow = (index: number) => {
    setEditingModels(prev => prev.filter((_, i) => i !== index))
  }

  const columns: ColumnsType<ModelInfo> = [
    { title: '模型名', dataIndex: 'name', width: 180, render: (t) => <Text code>{t}</Text> },
    { title: '显示名', dataIndex: 'display_name', width: 160 },
    {
      title: '上下文长度',
      dataIndex: 'context_length',
      width: 110,
      render: (v) => v ? `${(v / 1000).toFixed(0)}K` : '-',
    },
    {
      title: '最大 Token',
      dataIndex: 'max_tokens',
      width: 100,
      render: (v) => v ? v.toLocaleString() : '-',
    },
    {
      title: '输入价格',
      dataIndex: 'input_price_per_1k',
      width: 100,
      render: (v) => (v != null ? `¥${v}/1K` : '-'),
    },
    {
      title: '输出价格',
      dataIndex: 'output_price_per_1k',
      width: 100,
      render: (v) => (v != null ? `¥${v}/1K` : '-'),
    },
    { title: '状态', dataIndex: 'is_deprecated', width: 80, render: (v) => v ? <Tag color="default">已弃用</Tag> : <Tag color="success">可用</Tag> },
  ]

  // 按 provider 分组的 Tab 内容
  const tabItems = safeCatalogs.map(cat => ({
    key: cat.provider,
    label: `${cat.provider_name || cat.provider} (${cat.models.length})`,
    children: (
      <Table
        dataSource={cat.models}
        columns={columns}
        rowKey="name"
        pagination={false}
        size="small"
        locale={{ emptyText: <Empty description="暂无模型数据" /> }}
      />
    ),
  }))

  return (
    <div>
      {/* 操作栏 */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
        <Title level={5} style={{ margin: 0 }}>模型目录</Title>
        <Space>
          <Button icon={<ReloadOutlined />} onClick={loadCatalogs} loading={loading}>
            刷新
          </Button>
          <Button icon={<CloudDownloadOutlined />} onClick={handleInitDefault}>
            初始化默认
          </Button>
        </Space>
      </div>

      {/* 厂家操作卡片 */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))', gap: 12, marginBottom: 16 }}>
        {providers.map(p => {
          const hasCatalog = catalogs.some(c => c.provider === p.name)
          const modelCount = catalogs.find(c => c.provider === p.name)?.models.length ?? 0
          return (
            <Card key={p.id} size="small" hoverable>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <div>
                  <Text strong>{p.display_name}</Text>
                  <br />
                  <Text type="secondary" style={{ fontSize: 12 }}>{p.name}</Text>
                  {hasCatalog && <Tag style={{ marginLeft: 8 }} color="processing">{modelCount} 模型</Tag>}
                </div>
                <Space size="small">
                  <Button
                    size="small"
                    icon={<CloudDownloadOutlined />}
                    loading={fetchingModels === p.id}
                    onClick={() => handleFetchModels(p.id!, p.display_name)}
                    title="从 API 拉取模型列表"
                  />
                  <Button size="small" icon={<EditOutlined />} onClick={() => handleEditCatalog(p.name)} />
                  {hasCatalog && (
                    <Popconfirm title="确定删除该模型目录？" onConfirm={() => handleDeleteCatalog(p.name)}>
                      <Button size="small" danger icon={<DeleteOutlined />} />
                    </Popconfirm>
                  )}
                </Space>
              </div>
            </Card>
          )
        })}
      </div>

      {/* 已有目录的 Tab 展示 */}
      {catalogs.length > 0 && (
        <Tabs items={tabItems} size="small" />
      )}

      {/* 编辑弹窗 */}
      <Modal
        title={`编辑模型目录：${editingProvider}`}
        open={editModalOpen}
        onCancel={() => setEditModalOpen(false)}
        onOk={handleSaveCatalog}
        width={900}
        destroyOnHidden
      >
        <div style={{ marginBottom: 12, display: 'flex', justifyContent: 'flex-end' }}>
          <Button size="small" icon={<PlusOutlined />} onClick={addModelRow}>
            添加模型
          </Button>
        </div>
        <Table
          dataSource={editingModels.map((m, i) => ({ ...m, _key: `model-${i}` }))}
          rowKey="_key"
          pagination={false}
          size="small"
          scroll={{ x: 800 }}
          columns={[
            {
              title: '模型名',
              dataIndex: 'name',
              width: 160,
              render: (val, _, i) => (
                <Input size="small" value={val} onChange={e => updateModelRow(i, 'name', e.target.value)} />
              ),
            },
            {
              title: '显示名',
              dataIndex: 'display_name',
              width: 140,
              render: (val, _, i) => (
                <Input size="small" value={val} onChange={e => updateModelRow(i, 'display_name', e.target.value)} />
              ),
            },
            {
              title: '上下文(K)',
              dataIndex: 'context_length',
              width: 90,
              render: (val, _, i) => (
                <Input size="small" type="number" value={val} onChange={e => updateModelRow(i, 'context_length', Number(e.target.value))} />
              ),
            },
            {
              title: '最大Token',
              dataIndex: 'max_tokens',
              width: 90,
              render: (val, _, i) => (
                <Input size="small" type="number" value={val} onChange={e => updateModelRow(i, 'max_tokens', Number(e.target.value))} />
              ),
            },
            {
              title: '输入价',
              dataIndex: 'input_price_per_1k',
              width: 85,
              render: (val, _, i) => (
                <Input size="small" type="number" step="0.001" value={val} onChange={e => updateModelRow(i, 'input_price_per_1k', Number(e.target.value))} />
              ),
            },
            {
              title: '输出价',
              dataIndex: 'output_price_per_1k',
              width: 85,
              render: (val, _, i) => (
                <Input size="small" type="number" step="0.001" value={val} onChange={e => updateModelRow(i, 'output_price_per_1k', Number(e.target.value))} />
              ),
            },
            {
              title: '操作',
              width: 50,
              render: (_, __, i) => (
                <Button size="small" type="text" danger icon={<DeleteOutlined />} onClick={() => removeModelRow(i)} />
              ),
            },
          ]}
        />
      </Modal>
    </div>
  )
}
