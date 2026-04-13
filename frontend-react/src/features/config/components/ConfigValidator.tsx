/**
 * 配置验证器
 * 检测缺失的关键配置项并展示警告信息
 */

import { useState, useEffect, useMemo } from 'react'
import { Card, Alert, Tag, Button, Space, Typography, Spin, Empty, Descriptions } from 'antd'
import {
  WarningOutlined, CheckCircleOutlined, InfoCircleOutlined, ReloadOutlined,
} from '@ant-design/icons'
import type { SystemConfigResponse, SettingMetaItem } from '@/types/config.types'
import { getSystemConfig, getSystemSettingsMeta } from '@/services/api/config'

const { Text, Paragraph } = Typography

interface ValidationIssue {
  type: 'error' | 'warning' | 'info'
  category: string
  message: string
  detail?: string
}

interface ConfigValidatorProps {
  lastRefresh?: number
}

export default function ConfigValidator({ lastRefresh }: ConfigValidatorProps) {
  const [issues, setIssues] = useState<ValidationIssue[]>([])
  const [loading, setLoading] = useState(false)
  const [, setSystemConfig] = useState<SystemConfigResponse | null>(null)
  const [, setSettingsMeta] = useState<SettingMetaItem[]>([])

  const validate = async () => {
    setLoading(true)
    try {
      const [configRes, metaRes] = await Promise.all([
        getSystemConfig().catch(() => null),
        getSystemSettingsMeta().catch(() => null),
      ])

      const config = configRes?.data
      setSystemConfig(config ?? null)
      setSettingsMeta(metaRes?.data?.data?.items ?? [])

      const newIssues: ValidationIssue[] = []

      if (!config) {
        newIssues.push({ type: 'error', category: '系统', message: '无法获取系统配置' })
        setIssues(newIssues)
        return
      }

      // 1. LLM 配置检查
      if (!config.llm_configs || config.llm_configs.length === 0) {
        newIssues.push({ type: 'error', category: 'LLM', message: '未配置任何大模型', detail: '至少需要配置一个启用的 LLM 模型才能进行分析' })
      } else {
        const activeProviders = new Set(config.llm_configs.map(c => c.provider))
        if (activeProviders.size === 0) {
          newIssues.push({ type: 'warning', category: 'LLM', message: '所有模型均被禁用' })
        }
      }

      // 2. 默认 LLM 检查
      if (!config.default_llm) {
        newIssues.push({ type: 'warning', category: 'LLM', message: '未设置默认分析模型' })
      }

      // 3. 数据源检查
      if (!config.data_source_configs || config.data_source_configs.length === 0) {
        newIssues.push({ type: 'error', category: '数据源', message: '未配置任何数据源', detail: '需要至少一个启用的数据源才能获取股票数据' })
      } else {
        const hasActiveDS = config.data_source_configs.some(ds => ds.enabled)
        if (!hasActiveDS) {
          newIssues.push({ type: 'warning', category: '数据源', message: '所有数据源均被禁用' })
        }
      }

      // 4. 默认数据源检查
      if (!config.default_data_source) {
        newIssues.push({ type: 'warning', category: '数据源', message: '未设置默认数据源' })
      }

      // 5. 数据库配置检查
      if (!config.database_configs || config.database_configs.length === 0) {
        newIssues.push({ type: 'info', category: '数据库', message: '未配置数据库连接' })
      }

      // 6. 系统设置关键项检查
      if (metaRes?.data?.data?.items) {
        const meta = metaRes.data.data.items
        const quickAnalysisModel = meta.find((m: SettingMetaItem) => m.key === 'quick_analysis_model')
        const deepAnalysisModel = meta.find((m: SettingMetaItem) => m.key === 'deep_analysis_model')

        if (quickAnalysisModel && !quickAnalysisModel.has_value) {
          newIssues.push({ type: 'warning', category: '设置', message: '未设置快速分析模型' })
        }
        if (deepAnalysisModel && !deepAnalysisModel.has_value) {
          newIssues.push({ type: 'warning', category: '设置', message: '未设置深度分析模型' })
        }
      }

      setIssues(newIssues)
    } catch {
      setIssues([{ type: 'error', category: '系统', message: '配置验证失败，无法连接后端' }])
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { validate() }, [lastRefresh])

  const errorCount = issues.filter(i => i.type === 'error').length
  const warningCount = issues.filter(i => i.type === 'warning').length
  const infoCount = issues.filter(i => i.type === 'info').length

  const summary = useMemo(() => {
    if (issues.length === 0) return null
    return (
      <Descriptions size="small" column={3} style={{ marginBottom: 12 }}>
        <Descriptions.Item label={
          <span><WarningOutlined style={{ color: '#ff4d4f', marginRight: 4 }} />问题</span>
        }>
          <Tag color="error">{errorCount}</Tag>
        </Descriptions.Item>
        <Descriptions.Item label={
          <span><WarningOutlined style={{ color: '#d48806', marginRight: 4 }} />警告</span>
        }>
          <Tag color="warning">{warningCount}</Tag>
        </Descriptions.Item>
        <Descriptions.Item label={
          <span><InfoCircleOutlined style={{ color: '#4a7db8', marginRight: 4 }} />提示</span>
        }>
          <Tag color="info">{infoCount}</Tag>
        </Descriptions.Item>
      </Descriptions>
    )
  }, [issues, errorCount, warningCount, infoCount])

  return (
    <Card
      size="small"
      title={
        <Space>
          <span>配置健康检查</span>
          {issues.length > 0 && summary}
        </Space>
      }
      extra={
        <Button size="small" icon={<ReloadOutlined />} onClick={validate} loading={loading}>
          重新检测
        </Button>
      }
    >
      <Spin spinning={loading}>
        {issues.length === 0 ? (
          <Empty
            image={Empty.PRESENTED_IMAGE_SIMPLE}
            description={
              <span>
                <CheckCircleOutlined style={{ color: '#52c41a', marginRight: 8 }} />
                所有配置项正常，未发现问题
              </span>
            }
          />
        ) : (
          <div>
            {issues.map((item, idx) => (
              <div key={`${item.category}-${item.message}-${idx}`} style={{ padding: '8px 0' }}>
                <Alert
                  type={item.type === 'error' ? 'error' : item.type === 'warning' ? 'warning' : 'info'}
                  showIcon
                  banner
                  title={
                    <span>
                      <Tag>{item.category}</Tag>
                      <Text strong>{item.message}</Text>
                      {item.detail && <Paragraph type="secondary" style={{ margin: '4px 0 0', fontSize: 12 }}>{item.detail}</Paragraph>}
                    </span>
                  }
                  style={{ margin: 0 }}
                />
              </div>
            ))}
          </div>
        )}
      </Spin>
    </Card>
  )
}
