/**
 * MCP 工具卡片组件
 * 展示单个工具的名称、描述、状态，支持启用/禁用切换
 */

import { Tag, Switch, Typography, Space } from 'antd'
import { CheckCircleOutlined, CloseCircleOutlined } from '@ant-design/icons'
import type { MCPToolInfo } from '@/services/api/tools'

const { Text, Paragraph } = Typography

interface ToolCardProps {
  tool: MCPToolInfo
  onToggle?: (name: string, enabled: boolean) => void
  toggling?: boolean
}

export default function ToolCard({ tool, onToggle, toggling = false }: ToolCardProps) {
  return (
    <div
      style={{
        padding: '10px 12px',
        border: '1px solid #f0f0f0',
        borderRadius: 6,
        marginBottom: 8,
        background: '#fff',
        display: 'flex',
        alignItems: 'flex-start',
        justifyContent: 'space-between',
        gap: 12,
      }}
    >
      <div style={{ flex: 1, minWidth: 0 }}>
        <Space size={4} wrap>
          <Text code strong style={{ fontSize: 13 }}>{tool.name}</Text>
          <Tag color="blue" style={{ marginLeft: 4 }}>{tool.category}</Tag>
          {tool.tushare_only && <Tag color="purple">仅 Tushare</Tag>}
          {!tool.available && <Tag color="default">不可用</Tag>}
        </Space>
        <Paragraph
          type="secondary"
          ellipsis={{ rows: 2 }}
          style={{ margin: '4px 0 0', fontSize: 12 }}
        >
          {tool.description}
        </Paragraph>
      </div>

      <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 4, flexShrink: 0 }}>
        <span style={{
          fontSize: 11,
          color: tool.available ? '#52C41A' : '#FF4D4F',
          display: 'flex',
          alignItems: 'center',
          gap: 3,
        }}>
          {tool.available ? <CheckCircleOutlined /> : <CloseCircleOutlined />}
          {tool.available ? '可用' : '不可用'}
        </span>
        <Switch
          size="small"
          checked={tool.enabled}
          disabled={!tool.available || toggling}
          onChange={(checked) => onToggle?.(tool.name, checked)}
          checkedChildren="启用"
          unCheckedChildren="禁用"
        />
      </div>
    </div>
  )
}
