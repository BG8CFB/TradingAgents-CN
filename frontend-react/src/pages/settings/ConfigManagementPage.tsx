/**
 * 配置管理页面
 * 左侧菜单 + 右侧内容区布局，集成所有配置管理子模块：
 * - LLM 厂家管理（ProviderDialog）
 * - 模型目录管理（ModelCatalogManager）
 * - 数据源配置（DataSourceConfigDialog + SortableDataSourceList）
 * - 市场分类管理（MarketCategoryManager）
 * - 数据库配置管理
 * - 系统设置
 * - 配置验证器（ConfigValidator）
 * - 导入导出面板（ImportExportPanel）
 */

import { useState, useCallback } from 'react'
import {
  Layout, Menu, Card, Table, Button, Space, Tag, Switch, message,
  Popconfirm, Typography, Spin, Tabs, Empty, Alert, Form, Modal, Input, Select, InputNumber,
} from 'antd'
import {
  PlusOutlined, EditOutlined, DeleteOutlined, ReloadOutlined,
  SettingOutlined, CloudServerOutlined, DatabaseOutlined,
  ApiOutlined, ExportOutlined,
  SafetyCertificateOutlined, ToolOutlined,
} from '@ant-design/icons'
import type { ColumnsType } from 'antd/es/table'
import { useProviders } from '@/features/config/hooks/useProviders'
import { useConfig } from '@/features/config/hooks/useConfig'
import ProviderDialog from '@/features/config/components/ProviderDialog'
import ModelCatalogManager from '@/features/config/components/ModelCatalogManager'
import DataSourceConfigDialog from '@/features/config/components/DataSourceConfigDialog'
import MarketCategoryManager from '@/features/config/components/MarketCategoryManager'
import SortableDataSourceList from '@/features/config/components/SortableDataSourceList'
import ConfigValidator from '@/features/config/components/ConfigValidator'
import ImportExportPanel from '@/features/config/components/ImportExportPanel'
import type {
  LLMProviderResponse, LLMProviderRequest, DataSourceConfig,
  DataSourceConfigRequest, DatabaseConfig, DatabaseConfigRequest,
} from '@/types/config.types'

const { Sider, Content } = Layout
const { Text, Title } = Typography

/** 左侧菜单项定义 */
const SIDEBAR_MENU_ITEMS = [
  { key: 'providers', icon: <ApiOutlined />, label: 'LLM 厂家' },
  { key: 'models', icon: <SettingOutlined />, label: '模型目录' },
  { key: 'datasources', icon: <CloudServerOutlined />, label: '数据源' },
  { key: 'categories', icon: <ToolOutlined />, label: '市场分类' },
  { key: 'database', icon: <DatabaseOutlined />, label: '数据库' },
  { key: 'settings', icon: <SafetyCertificateOutlined />, label: '系统设置' },
  { key: 'validator', icon: <SafetyCertificateOutlined />, label: '配置检查' },
  { key: 'import_export', icon: <ExportOutlined />, label: '导入/导出' },
]

export default function ConfigManagementPage() {
  const [activeMenu, setActiveMenu] = useState('providers')
  const [providerDialogOpen, setProviderDialogOpen] = useState(false)
  const [editingProvider, setEditingProvider] = useState<LLMProviderResponse | null>(null)
  const [dsDialogOpen, setDsDialogOpen] = useState(false)
  const [editingDS, setEditingDS] = useState<DataSourceConfig | null>(null)
  const [dbDialogOpen, setDbDialogOpen] = useState(false)
  const [editingDB, setEditingDB] = useState<DatabaseConfig | null>(null)
  const [selectedCategoryId, setSelectedCategoryId] = useState<string | null>(null)

  const providersHook = useProviders()
  const configHook = useConfig()

  /** 全局刷新 */
  const handleGlobalRefresh = useCallback(async () => {
    await Promise.all([providersHook.refresh(), configHook.refresh()])
  }, [providersHook, configHook])

  // ========== LLM 厂家操作 ==========

  const handleAddProvider = () => {
    setEditingProvider(null)
    setProviderDialogOpen(true)
  }

  const handleEditProvider = (record: LLMProviderResponse) => {
    setEditingProvider(record)
    setProviderDialogOpen(true)
  }

  const handleSaveProvider = async (data: LLMProviderRequest) => {
    if (editingProvider) {
      await providersHook.updateProvider(editingProvider.id!, data)
    } else {
      await providersHook.addProvider(data)
    }
  }

  // ========== 数据源操作 ==========

  const handleAddDS = () => {
    setEditingDS(null)
    setDsDialogOpen(true)
  }

  const handleEditDS = (record: DataSourceConfig) => {
    setEditingDS(record)
    setDsDialogOpen(true)
  }

  const handleSaveDS = async (data: DataSourceConfigRequest) => {
    if (editingDS) {
      await configHook.updateDataSource(editingDS.name, data)
    } else {
      await configHook.addDataSource(data)
    }
  }

  // ========== 数据库操作 ==========

  const handleAddDB = () => {
    setEditingDB(null)
    setDbDialogOpen(true)
  }

  const handleEditDB = (record: DatabaseConfig) => {
    setEditingDB(record)
    setDbDialogOpen(true)
  }

  const handleSaveDB = async (data: DatabaseConfigRequest) => {
    if (editingDB) {
      await configHook.updateDatabase(editingDB.name, data)
    } else {
      await configHook.addDatabase(data)
    }
  }

  // ========== 渲染各子页面内容 ==========

  const renderContent = () => {
    switch (activeMenu) {
      case 'providers':
        return renderProvidersTab()
      case 'models':
        return (
          <ModelCatalogManager
            providers={providersHook.providers}
            onRefresh={handleGlobalRefresh}
          />
        )
      case 'datasources':
        return renderDataSourcesTab()
      case 'categories':
        return (
          <MarketCategoryManager onRefresh={handleGlobalRefresh} />
        )
      case 'database':
        return renderDatabaseTab()
      case 'settings':
        return renderSettingsTab()
      case 'validator':
        return (
          <div>
            <ConfigValidator key={`validator-${activeMenu}`} />
            <ImportExportPanel onImported={handleGlobalRefresh} />
          </div>
        )
      case 'import_export':
        return <ImportExportPanel onImported={handleGlobalRefresh} />
      default:
        return <Empty description="请选择左侧菜单" />
    }
  }

  // ---------- LLM 厂家表格 ----------
  const renderProvidersTab = () => {
    const columns: ColumnsType<LLMProviderResponse> = [
      { title: '标识名', dataIndex: 'name', width: 120, render: t => <Text code>{t}</Text> },
      { title: '显示名称', dataIndex: 'display_name', width: 140 },
      {
        title: 'API Key',
        dataIndex: 'api_key',
        width: 160,
        render: v => v ? <Text copyable style={{ fontSize: 12 }}>{v}</Text> : <Text type="secondary">未配置</Text>,
      },
      {
        title: '状态',
        dataIndex: 'is_active',
        width: 80,
        render: (v, record) => (
          <Switch
            size="small"
            checked={v}
            onChange={(checked) => providersHook.toggleProvider(record.id!, checked)}
            checkedChildren="启用"
            unCheckedChildren="禁用"
          />
        ),
      },
      {
        title: '类型',
        width: 90,
        render: (_, r) => r.is_aggregator ? <Tag color="purple">聚合</Tag> : <Tag color="blue">直连</Tag>,
      },
      { title: '功能', dataIndex: 'supported_features', width: 200, render: (tags: string[]) => tags?.map((t: string) => <Tag key={t}>{t}</Tag>) },
      {
        title: '操作',
        width: 160,
        render: (_, record) => (
          <Space size="small">
            <Button size="small" icon={<EditOutlined />} onClick={() => handleEditProvider(record)} />
            <Popconfirm title={`确定删除厂家「${record.display_name}」？`} onConfirm={() => providersHook.deleteProvider(record.id!)}>
              <Button size="small" danger icon={<DeleteOutlined />} />
            </Popconfirm>
          </Space>
        ),
      },
    ]

    return (
      <div>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
          <Title level={5} style={{ margin: 0 }}>LLM 厂家管理</Title>
          <Space>
            <Button icon={<ReloadOutlined />} onClick={providersHook.refresh} loading={providersHook.loading}>刷新</Button>
            <Button type="primary" icon={<PlusOutlined />} onClick={handleAddProvider}>添加厂家</Button>
          </Space>
        </div>

        {/* 快捷操作 */}
        <Card size="small" style={{ marginBottom: 12 }}>
          <Space wrap>
            <Button size="small" onClick={() => providersHook.migrateFromEnv().then(r => message[r.success ? 'success' : 'error'](r.message))}>
              从环境变量迁移
            </Button>
            <Button size="small" onClick={() => providersHook.initAggregators().then(r => message[r.success ? 'success' : 'error'](r.message))}>
              初始化聚合渠道
            </Button>
            <Button size="small" onClick={() => configHook.reloadSystemConfig()}>
              重载配置
            </Button>
          </Space>
        </Card>

        <Table
          dataSource={providersHook.providers}
          columns={columns}
          rowKey="id"
          loading={providersHook.loading}
          pagination={false}
          size="small"
          locale={{ emptyText: '暂无 LLM 厂家配置，点击"添加厂家"创建' }}
        />

        <ProviderDialog
          open={providerDialogOpen}
          provider={editingProvider}
          onClose={() => setProviderDialogOpen(false)}
          onSave={handleSaveProvider}
        />
      </div>
    )
  }

  // ---------- 数据源表格 ----------
  const renderDataSourcesTab = () => {
    const dsColumns: ColumnsType<DataSourceConfig> = [
      { title: '标识名', dataIndex: 'name', width: 130, render: t => <Text code>{t}</Text> },
      { title: '显示名称', dataIndex: 'display_name', width: 140 },
      { title: '类型', dataIndex: 'type', width: 100, render: t => <Tag color="blue">{t}</Tag> },
      {
        title: 'API Key',
        dataIndex: 'api_key',
        width: 150,
        render: v => v ? <Text style={{ fontSize: 12 }}>{v}</Text> : <Text type="secondary">-</Text>,
      },
      {
        title: '启用',
        dataIndex: 'enabled',
        width: 70,
        render: v => v ? <Tag color="success">是</Tag> : <Tag color="default">否</Tag>,
      },
      { title: '优先级', dataIndex: 'priority', width: 70, sorter: (a, b) => (a.priority ?? 0) - (b.priority ?? 0) },
      {
        title: '默认',
        width: 70,
        render: (_, r) =>
          configHook.systemConfig?.default_data_source === r.name
            ? <Tag color="gold">默认</Tag> : null,
      },
      {
        title: '操作',
        width: 180,
        render: (_, record) => (
          <Space size="small">
            <Button size="small" icon={<EditOutlined />} onClick={() => handleEditDS(record)} />
            <Button
              size="small"
              disabled={configHook.systemConfig?.default_data_source === record.name}
              onClick={() => configHook.setDefaultDS(record.name)}
            >
              设默认
            </Button>
            <Popconfirm title={`确定删除数据源「${record.display_name || record.name}」？`} onConfirm={() => configHook.deleteDataSource(record.name)}>
              <Button size="small" danger icon={<DeleteOutlined />} />
            </Popconfirm>
          </Space>
        ),
      },
    ]

    return (
      <div>
        <Tabs
          defaultActiveKey="list"
          items={[
            {
              key: 'list',
              label: `数据源列表 (${configHook.dataSources.length})`,
              children: (
                <div>
                  <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 12 }}>
                    <Text strong>数据源配置列表</Text>
                    <Space>
                      <Button size="small" icon={<ReloadOutlined />} onClick={configHook.refresh} loading={configHook.loading}>刷新</Button>
                      <Button type="primary" size="small" icon={<PlusOutlined />} onClick={handleAddDS}>添加数据源</Button>
                    </Space>
                  </div>
                  <Table dataSource={configHook.dataSources} columns={dsColumns} rowKey="name" loading={configHook.loading} pagination={false} size="small" />
                </div>
              ),
            },
            {
              key: 'sort',
              label: '优先级排序',
              children: (
                <div>
                  <div style={{ marginBottom: 12 }}>
                    <Text type="secondary">选择市场分类后可查看和调整该分类下数据源的优先级顺序：</Text>
                  </div>
                  <div style={{ display: 'flex', gap: 12 }}>
                    <div style={{ minWidth: 200 }}>
                      <Text strong style={{ display: 'block', marginBottom: 8 }}>选择分类</Text>
                      <Menu
                        mode="inline"
                        selectedKeys={selectedCategoryId ? [selectedCategoryId] : []}
                        onSelect={({ key }) => setSelectedCategoryId(key)}
                        items={configHook.categories.map(c => ({ key: c.id, label: `${c.display_name}` }))}
                        style={{ borderRight: '1px solid var(--border-color)' }}
                      />
                    </div>
                    <div style={{ flex: 1 }}>
                      <SortableDataSourceList
                        category={configHook.categories.find(c => c.id === selectedCategoryId) ?? null}
                        onRefresh={configHook.refresh}
                      />
                    </div>
                  </div>
                </div>
              ),
            },
          ]}
        />

        <DataSourceConfigDialog
          open={dsDialogOpen}
          dataSource={editingDS}
          categories={configHook.categories}
          onClose={() => setDsDialogOpen(false)}
          onSave={handleSaveDS}
        />
      </div>
    )
  }

  // ---------- 数据库配置表格 ----------
  const renderDatabaseTab = () => {
    const dbColumns: ColumnsType<DatabaseConfig> = [
      { title: '名称', dataIndex: 'name', width: 130, render: t => <Text code>{t}</Text> },
      { title: '类型', dataIndex: 'type', width: 110, render: t => <Tag color="geekblue">{t}</Tag> },
      { title: '地址', width: 200, render: (_, r) => <Text>{r.host}:{r.port}</Text> },
      { title: '用户名', dataIndex: 'username', width: 100 },
      { title: '密码', dataIndex: 'password', width: 80, render: v => v ? '******' : <Text type="secondary">无</Text> },
      { title: '数据库', dataIndex: 'database', width: 100 },
      {
        title: '启用',
        dataIndex: 'enabled',
        width: 70,
        render: v => v ? <Tag color="success">是</Tag> : <Tag color="default">否</Tag>,
      },
      {
        title: '操作',
        width: 200,
        render: (_, record) => (
          <Space size="small">
            <Button size="small" icon={<EditOutlined />} onClick={() => handleEditDB(record)} />
            <Button
              size="small"
              onClick={async () => {
                try {
                  const result = await configHook.testDatabase(record.name)
                  message[result.success ? 'success' : 'error'](result.message)
                } catch {
                  message.error('测试失败')
                }
              }}
            >
              测试连接
            </Button>
            <Popconfirm title={`确定删除数据库「${record.name}」？`} onConfirm={() => configHook.deleteDatabase(record.name)}>
              <Button size="small" danger icon={<DeleteOutlined />} />
            </Popconfirm>
          </Space>
        ),
      },
    ]

    return (
      <div>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
          <Title level={5} style={{ margin: 0 }}>数据库配置管理</Title>
          <Space>
            <Button icon={<ReloadOutlined />} onClick={configHook.refresh} loading={configHook.loading}>刷新</Button>
            <Button type="primary" icon={<PlusOutlined />} onClick={handleAddDB}>添加数据库</Button>
          </Space>
        </div>

        <Table
          dataSource={configHook.databases}
          columns={dbColumns}
          rowKey="name"
          loading={configHook.loading}
          pagination={false}
          size="small"
          locale={{ emptyText: '暂无数据库配置' }}
        />

        {/* 数据库编辑弹窗（简化内联） */}
        <Modal
          title={editingDB ? `编辑数据库：${editingDB.name}` : '添加数据库'}
          open={dbDialogOpen}
          onCancel={() => setDbDialogOpen(false)}
          onOk={() => { /* 由 DBForm 内部 Form.onFinish 触发提交 */ }}
          width={560}
          destroyOnHidden
        >
          <DBForm initialValues={editingDB} onSubmit={handleSaveDB} />
        </Modal>
      </div>
    )
  }

  // ---------- 系统设置渲染 ----------
  const renderSettingsTab = () => {
    const entries = Object.entries(configHook.settings)

    if (entries.length === 0 && !configHook.loading) {
      return <Empty description="暂无系统设置数据" />
    }

    return (
      <div>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
          <Title level={5} style={{ margin: 0 }}>系统设置</Title>
          <Button icon={<ReloadOutlined />} onClick={configHook.refresh} loading={configHook.loading}>
            刷新
          </Button>
        </div>

        <Alert
          type="info"
          showIcon
          title="修改系统设置后将立即生效，部分设置可能需要重载配置才能完全生效。"
          style={{ marginBottom: 16 }}
        />

        <Card size="small">
          {entries.map(([key, value]) => {
            const isSensitive = ['password', 'secret', 'token', 'key'].some(s => key.toLowerCase().includes(s))
            return (
              <div key={key} style={{ display: 'flex', justifyContent: 'space-between', padding: '8px 0', borderBottom: '1px solid #f0f0f0' }}>
                <div>
                  <Text code>{key}</Text>
                  {isSensitive && <Tag color="warning" style={{ marginLeft: 6 }}>敏感</Tag>}
                </div>
                <div style={{ maxWidth: '50%' }}>
                  {value == null || value === '' ? (
                    <Text type="secondary">未设置</Text>
                  ) : isSensitive ? (
                    <Text type="secondary">***已配置***</Text>
                  ) : typeof value === 'boolean' ? (
                    <Switch
                      size="small"
                      checked={Boolean(value)}
                      onChange={(checked) => configHook.updateSettings({ [key]: checked })}
                    />
                  ) : (
                    <Text>{String(value)}</Text>
                  )}
                </div>
              </div>
            )
          })}
        </Card>
      </div>
    )
  }

  return (
    <Layout style={{ background: 'transparent', minHeight: 500 }}>
      <Sider width={200} style={{ background: 'transparent', borderRight: '1px solid var(--border-color)' }}>
        <Menu
          mode="inline"
          selectedKeys={[activeMenu]}
          onClick={({ key }) => setActiveMenu(key as string)}
          items={SIDEBAR_MENU_ITEMS.map(item => ({
            key: item.key,
            icon: item.icon,
            label: item.label,
          }))}
          style={{ borderRight: 'none', paddingTop: 8, paddingBottom: 8 }}
        />
      </Sider>
      <Content style={{ paddingLeft: 24, overflowY: 'auto' }}>
        <Spin spinning={configHook.loading && activeMenu !== 'providers'}>
          {renderContent()}
        </Spin>
      </Content>
    </Layout>
  )
}

// ========== 内联：数据库表单组件 ==========
function DBForm({ initialValues, onSubmit }: { initialValues?: DatabaseConfig | null; onSubmit: (data: DatabaseConfigRequest) => Promise<void> }) {
  const [form] = Form.useForm<DatabaseConfigRequest>()

  // 注意：这里简化处理，实际使用时需要更完善的表单逻辑
  return (
    <Form
      form={form}
      layout="vertical"
      initialValues={initialValues ?? { type: 'mongodb', enabled: true, pool_size: 10, max_overflow: 20 }}
      onFinish={async (values) => {
        await onSubmit(values)
      }}
    >
      <Form.Item name="name" label="名称" rules={[{ required: true }]}>
        <Input disabled={!!initialValues} />
      </Form.Item>
      <Form.Item name="type" label="类型" rules={[{ required: true }]}>
        <Select options={[
          { value: 'mongodb', label: 'MongoDB' },
          { value: 'mysql', label: 'MySQL' },
          { value: 'postgresql', label: 'PostgreSQL' },
          { value: 'redis', label: 'Redis' },
          { value: 'sqlite', label: 'SQLite' },
        ]} />
      </Form.Item>
      <Space style={{ width: '100%' }} wrap>
        <Form.Item name="host" label="主机" rules={[{ required: true }]} style={{ flex: 2, minWidth: 180 }}>
          <Input placeholder="localhost" />
        </Form.Item>
        <Form.Item name="port" label="端口" rules={[{ required: true }]} style={{ flex: 1, minWidth: 100 }}>
          <InputNumber min={1} max={65535} style={{ width: '100%' }} />
        </Form.Item>
      </Space>
      <Form.Item name="username" label="用户名">
        <Input />
      </Form.Item>
      <Form.Item name="password" label="密码">
        <Input.Password placeholder={initialValues ? '留空不修改' : '请输入密码'} />
      </Form.Item>
      <Form.Item name="database" label="数据库名">
        <Input />
      </Form.Item>
      <Form.Item name="description" label="描述">
        <Input.TextArea rows={2} />
      </Form.Item>
      <Space>
        <Form.Item name="enabled" label="启用" valuePropName="checked">
          <Switch />
        </Form.Item>
        <Form.Item name="pool_size" label="连接池大小">
          <InputNumber min={1} max={100} defaultValue={10} />
        </Form.Item>
      </Space>
    </Form>
  )
}
