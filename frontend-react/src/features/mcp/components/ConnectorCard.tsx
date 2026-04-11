/**
 * MCP 连接器卡片组件
 * 展示单个 MCP 连接器的状态、健康信息，支持展开/折叠、启用/禁用切换、删除确认
 */

import {
  Card, Tag, Switch, Button, Typography, Alert, Descriptions, Popconfirm,
} from 'antd'
import {
  RightOutlined, CheckCircleFilled,
  CloseCircleFilled, MinusCircleFilled, QuestionCircleFilled,
  DeleteOutlined,
} from '@ant-design/icons'
import type { MCPConnector } from '@/services/api/mcp'

const { Text } = Typography

/** 状态颜色映射 */
const STATUS_CONFIG: Record<string, { color: string; label: string; icon: React.ReactNode }> = {
  connected:     { color: '#52C41A', label: '已连接',  icon: <CheckCircleFilled /> },
  healthy:       { color: '#52C41A', label: '健康',   icon: <CheckCircleFilled /> },
  disconnected:  { color: '#FF4D4F', label: '断开',   icon: <CloseCircleFilled /> },
  error:         { color: '#FF4D4F', label: '错误',   icon: <CloseCircleFilled /> },
  stopped:       { color: '#9CA3AF', label: '已停止', icon: <MinusCircleFilled /> },
  unavailable:   { color: '#FF4D4F', label: '不可达', icon: <CloseCircleFilled /> },
  unknown:       { color: '#9CA3AF', label: '未知',   icon: <QuestionCircleFilled /> },
}

const TYPE_TAG_COLOR: Record<string, string> = {
  stdio: 'blue',
  http: 'orange',
  'streamable-http': 'green',
}

interface ConnectorCardProps {
  connector: MCPConnector
  expanded?: boolean
  onToggleExpand?: (name: string) => void
  onToggleEnabled?: (name: string, enabled: boolean) => void
  onDelete?: (name: string) => void
  deleting?: boolean
}

/** 根据名称生成固定颜色 */
function getNameColor(name: string): string {
  const colors = ['#3b82f6', '#eab308', '#a855f7', '#06b6d4', '#ec4899', '#f97316']
  let hash = 0
  for (let i = 0; i < name.length; i++) {
    hash = name.charCodeAt(i) + ((hash << 5) - hash)
  }
  return colors[Math.abs(hash) % colors.length]
}

export default function ConnectorCard({
  connector,
  expanded = false,
  onToggleExpand,
  onToggleEnabled,
  onDelete,
  deleting = false,
}: ConnectorCardProps) {
  const statusCfg = STATUS_CONFIG[connector.status] ?? STATUS_CONFIG.unknown

  return (
    <Card
      size="small"
      style={{
        marginBottom: 12,
        borderLeft: `3px solid ${statusCfg.color}`,
        transition: 'box-shadow 0.2s',
      }}
      styles={{ body: { padding: '12px 16px' } }}
    >
      {/* 头部：基本信息行 */}
      <div
        style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', cursor: 'pointer' }}
        onClick={() => onToggleExpand?.(connector.name)}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <RightOutlined
            style={{
              fontSize: 10,
              color: '#9CA3AF',
              transition: 'transform 0.2s',
              transform: expanded ? 'rotate(90deg)' : 'none',
            }}
          />
          {/* 名称首字母图标 */}
          <div
            style={{
              width: 32, height: 32, borderRadius: 6,
              background: getNameColor(connector.name),
              color: '#fff', fontWeight: 600,
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              fontSize: 14, flexShrink: 0,
            }}
          >
            {connector.name.charAt(0).toUpperCase()}
          </div>
          <Text strong style={{ fontSize: 14 }}>{connector.name}</Text>
          <Tag color={TYPE_TAG_COLOR[connector.type] ?? 'default'}>{connector.type || 'stdio'}</Tag>
          <span style={{ color: statusCfg.color, fontSize: 12, display: 'flex', alignItems: 'center', gap: 4 }}>
            {statusCfg.icon}
            {statusCfg.label}
          </span>
        </div>

        <Switch
          size="small"
          checked={connector.enabled}
          onChange={(checked) => {
            onToggleEnabled?.(connector.name, checked)
          }}
          onClick={(e: unknown) => { if (e && typeof e === 'object' && 'stopPropagation' in e) (e as { stopPropagation: () => void }).stopPropagation() }}
          checkedChildren="启用"
          unCheckedChildren="禁用"
        />
      </div>

      {/* 展开详情 */}
      {expanded && (
        <div style={{ marginTop: 12, paddingTop: 12, borderTop: '1px solid #f0f0f0' }}>
          {/* 健康信息 */}
          {connector.healthInfo && (
            <Alert
              type={
                (connector.healthInfo as Record<string, unknown>).status === 'healthy' ||
                (connector.healthInfo as Record<string, unknown>).status === 'connected'
                  ? 'success'
                  : (connector.healthInfo as Record<string, unknown>).status === 'error' ||
                    (connector.healthInfo as Record<string, unknown>).status === 'disconnected'
                    ? 'error'
                    : 'warning'
              }
              showIcon
              style={{ marginBottom: 12 }}
              message={
                <Descriptions size="small" column={2} colon={false}>
                  {(Object.entries(connector.healthInfo) as [string, unknown][]).map(([key, val]) => (
                    <Descriptions.Item key={key} label={key}>
                      {typeof val === 'number' && key.toLowerCase().includes('latency')
                        ? `${Number(val).toFixed(0)}ms`
                        : typeof val === 'string' && key.toLowerCase().includes('time')
                          ? new Date(val).toLocaleTimeString()
                          : String(val ?? '-')}
                    </Descriptions.Item>
                  ))}
                </Descriptions>
              }
            />
          )}

          {/* 操作按钮 */}
          <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
            {onDelete && (
              <Popconfirm
                title={`确定要删除「${connector.name}」吗？`}
                onConfirm={() => onDelete(connector.name)}
                okText="确定"
                cancelText="取消"
                okButtonProps={{ loading: deleting }}
              >
                <Button size="small" danger icon={<DeleteOutlined />}>
                  删除配置
                </Button>
              </Popconfirm>
            )}
          </div>
        </div>
      )}
    </Card>
  )
}
