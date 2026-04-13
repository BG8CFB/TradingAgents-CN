/**
 * MCP 服务管理页面
 * 功能：连接器列表、启用/禁用切换、健康检查、手动添加/删除配置
 */

import { useState, useCallback, useEffect } from 'react'
import {
  Card, Button, Space, Typography, Empty, Spin, message, Alert,
} from 'antd'
import {
  ReloadOutlined, PlusOutlined, QuestionCircleOutlined, ApiOutlined,
  MedicineBoxOutlined,
} from '@ant-design/icons'
import { useMCP } from '@/features/mcp/hooks/useMCP'
import ConnectorCard from '@/features/mcp/components/ConnectorCard'
import ConnectorForm from '@/features/mcp/components/ConnectorForm'

const { Title, Text } = Typography

export default function MCPManagementPage() {
  const mcp = useMCP()
  const [expandedItems, setExpandedItems] = useState<Set<string>>(new Set())
  const [formOpen, setFormOpen] = useState(false)
  const [deletingName, setDeletingName] = useState<string | null>(null)

  useEffect(() => {
    mcp.fetchConnectors()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const toggleExpand = (name: string) => {
    setExpandedItems(prev => {
      const next = new Set(prev)
      if (next.has(name)) next.delete(name)
      else next.add(name)
      return next
    })
  }

  const handleAdd = async (mcpServers: Record<string, unknown>) => {
    await mcp.batchUpdate(mcpServers)
    setFormOpen(false)
  }

  /** 确认删除 */
  const handleDelete = useCallback(async (name: string) => {
    setDeletingName(name)
    try {
      await mcp.removeConnector(name)
    } finally {
      setDeletingName(null)
    }
  }, [mcp])

  return (
    <div style={{ padding: '0 0 24px' }}>
      {/* 页面标题 */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 20 }}>
        <Space>
          <Title level={4} style={{ margin: 0 }}>
            <ApiOutlined style={{ marginRight: 8 }} />
            MCP 服务管理
          </Title>
          <Text type="secondary" style={{ fontSize: 13 }}>Model Context Protocol</Text>
          <QuestionCircleOutlined style={{ color: '#9CA3AF', cursor: 'pointer' }} />
        </Space>
        <Space>
          <Button icon={<ReloadOutlined />} onClick={mcp.fetchConnectors} loading={mcp.loading}>
            刷新
          </Button>
          <Button type="primary" icon={<PlusOutlined />} onClick={() => setFormOpen(true)}>
            添加连接器
          </Button>
        </Space>
      </div>

      {/* 连接器列表 */}
      <Spin spinning={mcp.loading}>
        {mcp.connectors.length === 0 && !mcp.loading ? (
          <Card>
            <Empty
              image={<MedicineBoxOutlined style={{ fontSize: 48, color: '#4A7DB8' }} />}
              description="暂无 MCP Server 配置"
            >
              <Button type="primary" onClick={() => setFormOpen(true)}>
                手动添加
              </Button>
            </Empty>
          </Card>
        ) : (
          <div>
            {mcp.connectors.map(connector => (
              <ConnectorCard
                key={connector.name}
                connector={connector}
                expanded={expandedItems.has(connector.name)}
                onToggleExpand={toggleExpand}
                onToggleEnabled={mcp.toggleConnector}
                onDelete={handleDelete}
                deleting={deletingName === connector.name}
              />
            ))}
          </div>
        )}
      </Spin>

      {/* 手动添加对话框 */}
      <ConnectorForm
        open={formOpen}
        onClose={() => setFormOpen(false)}
        onSubmit={handleAdd}
        submitting={mcp.saving}
      />

      {/* 健康检查结果 */}
      {mcp.healthData && Object.keys(mcp.healthData).length > 0 && (
        <Alert
          type="info"
          showIcon
          closable
          onClose={() => void 0}
          style={{ marginTop: 16 }}
          title="健康检查结果"
          description={
            <pre style={{ margin: 0, fontSize: 12, maxHeight: 200, overflow: 'auto' }}>
              {JSON.stringify(mcp.healthData, null, 2)}
            </pre>
          }
        />
      )}

      {/* 快捷操作 */}
      <Card size="small" style={{ marginTop: 16 }}>
        <Space wrap>
          <Button
            size="small"
            icon={<MedicineBoxOutlined />}
            onClick={async () => {
              await mcp.doHealthCheck()
              message.success('健康检查完成')
            }}
          >
            执行健康检查
          </Button>
          <Button
            size="small"
            onClick={async () => await mcp.doReload()}
          >
            重载配置
          </Button>
        </Space>
      </Card>
    </div>
  )
}
