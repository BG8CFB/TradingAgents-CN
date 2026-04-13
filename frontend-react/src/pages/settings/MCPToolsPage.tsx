/**
 * MCP 工具管理页面
 * 功能：工具列表、按类别分组、启用/禁用切换、可用性摘要
 */

import { useState, useEffect, useCallback } from 'react'
import {
  Card, Button, Space, Typography, Spin, Statistic, Row, Col, Tag, message, Alert,
} from 'antd'
import {
  ReloadOutlined, ToolOutlined, CheckCircleOutlined, CloseCircleOutlined,
} from '@ant-design/icons'
import { listMCPTools, toggleMCPTool, getMCPAvailabilitySummary, type MCPToolInfo } from '@/services/api/tools'
import ToolCategoryGroup from '@/features/mcp/components/ToolCategoryGroup'

const { Title, Text } = Typography

export default function MCPToolsPage() {
  const [tools, setTools] = useState<MCPToolInfo[]>([])
  const [loading, setLoading] = useState(false)
  const [togglingName, setTogglingName] = useState<string | null>(null)
  const [summary, setSummary] = useState<{
    total: number; available: number; unavailable: number
    enabled: number; disabled: number
    tushare_available: boolean
    by_category: Record<string, { total: number; available: number; enabled: number }>
    disabled_tools: string[]
  } | null>(null)

  /** 加载工具列表 */
  const fetchTools = useCallback(async () => {
    setLoading(true)
    try {
      const res = await listMCPTools()
      setTools((res as unknown as { data?: MCPToolInfo[] }).data ?? [])
      // 同时加载摘要
      try {
        const sumRes = await getMCPAvailabilitySummary()
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        const rawSummary = (sumRes as any).data
        setSummary(rawSummary ?? null)
      } catch {
        // 摘要加载失败不影响主功能
      }
    } catch {
      message.error('加载 MCP 工具列表失败')
      setTools([])
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    fetchTools()
  }, [fetchTools])

  /** 切换工具启用状态 */
  const handleToggle = async (name: string, enabled: boolean) => {
    setTogglingName(name)
    try {
      await toggleMCPTool(name, enabled)
      message.success(`${enabled ? '启用' : '禁用'}成功: ${name}`)
      // 刷新列表以获取最新状态
      await fetchTools()
    } catch {
      message.error('操作失败')
    } finally {
      setTogglingName(null)
    }
  }

  return (
    <div style={{ padding: '0 0 24px' }}>
      {/* 页面标题 */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 20 }}>
        <Space>
          <Title level={4} style={{ margin: 0 }}>
            <ToolOutlined style={{ marginRight: 8 }} />
            MCP 工具管理
          </Title>
        </Space>
        <Button icon={<ReloadOutlined />} onClick={fetchTools} loading={loading}>
          刷新
        </Button>
      </div>

      {/* 统计概览 */}
      {summary && (
        <Card size="small" style={{ marginBottom: 16 }}>
          <Row gutter={24}>
            <Col span={4}>
              <Statistic title="总工具数" value={summary.total} />
            </Col>
            <Col span={4}>
              <Statistic
                title="可用"
                value={summary.available}
                styles={{ content: { color: '#52C41A' } }}
                prefix={<CheckCircleOutlined />}
              />
            </Col>
            <Col span={4}>
              <Statistic
                title="不可用"
                value={summary.unavailable}
                styles={{ content: { color: '#FF4D4F' } }}
                prefix={<CloseCircleOutlined />}
              />
            </Col>
            <Col span={4}>
              <Statistic
                title="已启用"
                value={summary.enabled}
                styles={{ content: { color: '#C9A96E' } }}
              />
            </Col>
            <Col span={4}>
              <Statistic
                title="已禁用"
                value={summary.disabled}
                styles={{ content: { color: '#9CA3AF' } }}
              />
            </Col>
            <Col span={4}>
              <div>
                <Text type="secondary" style={{ fontSize: 12 }}>Tushare 状态</Text>
                <br />
                <Tag color={summary.tushare_available ? 'success' : 'error'} style={{ marginTop: 2 }}>
                  {summary.tushare_available ? '可用' : '不可用'}
                </Tag>
              </div>
            </Col>
          </Row>

          {/* 被禁用的工具提示 */}
          {summary.disabled_tools.length > 0 && (
            <Alert
              type="warning"
              showIcon
              style={{ marginTop: 12 }}
              title={`以下 ${summary.disabled_tools.length} 个工具已被禁用`}
              description={
                <Space wrap size={[4, 4]}>
                  {summary.disabled_tools.map(t => (
                    <Tag key={t}>{t}</Tag>
                  ))}
                </Space>
              }
            />
          )}
        </Card>
      )}

      {/* 工具列表（按类别分组） */}
      <Card>
        <Spin spinning={loading}>
          <ToolCategoryGroup
            tools={tools}
            loading={loading}
            onToggle={handleToggle}
            togglingName={togglingName}
          />
        </Spin>
      </Card>
    </div>
  )
}
