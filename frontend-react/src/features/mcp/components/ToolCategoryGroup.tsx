/**
 * MCP 工具按类别分组展示组件
 */

import { Typography, Empty, Spin, Collapse } from 'antd'
import { ToolOutlined } from '@ant-design/icons'
import type { MCPToolInfo } from '@/services/api/tools'
import ToolCard from './ToolCard'

const { Text } = Typography

interface ToolCategoryGroupProps {
  tools: MCPToolInfo[]
  loading?: boolean
  onToggle?: (name: string, enabled: boolean) => void
  togglingName?: string | null
}

/** 类别中文映射 */
const CATEGORY_LABELS: Record<string, string> = {
  '核心数据': '核心数据',
  '分钟数据': '分钟数据',
  '业绩数据': '业绩数据',
  '宏观资金': '宏观/资金',
  '基金数据': '基金数据',
  '指数其他': '指数/其他',
  '新闻时间': '新闻/时效',
}

export default function ToolCategoryGroup({
  tools,
  loading = false,
  onToggle,
  togglingName,
}: ToolCategoryGroupProps) {
  if (loading) {
    return (
      <div style={{ textAlign: 'center', padding: 40 }}>
        <Spin description="加载工具列表..." />
      </div>
    )
  }

  if (!tools.length) {
    return <Empty description="暂无 MCP 工具" />
  }

  // 按类别分组
  const grouped = tools.reduce<Record<string, MCPToolInfo[]>>((acc, tool) => {
    const cat = tool.category || '未分类'
    if (!acc[cat]) acc[cat] = []
    acc[cat].push(tool)
    return acc
  }, {})

  const categories = Object.entries(grouped).map(([category, items]) => ({
    key: category,
    label: (
      <span>
        <ToolOutlined style={{ marginRight: 8 }} />
        {CATEGORY_LABELS[category] || category}
        <Text type="secondary" style={{ marginLeft: 8, fontSize: 12 }}>
          ({items.length} 个)
        </Text>
      </span>
    ),
    children: (
      <div>
        {items.map(tool => (
          <ToolCard
            key={tool.name}
            tool={tool}
            onToggle={onToggle}
            toggling={togglingName === tool.name}
          />
        ))}
      </div>
    ),
  }))

  return (
    <Collapse
      defaultActiveKey={Object.keys(grouped)}
      ghost
      items={categories}
    />
  )
}
