/**
 * 缓存管理页面
 * 查看缓存统计、清理过期缓存、清空全部缓存、查看缓存详情
 */

import { useState, useCallback } from 'react'
import {
  Card, Table, Button, Space, Statistic, Row, Col, Tag, message,
  Popconfirm, Typography, Descriptions,
} from 'antd'
import {
  DeleteOutlined, ClearOutlined, ReloadOutlined,
  HddOutlined, FileTextOutlined, DatabaseOutlined,
} from '@ant-design/icons'
import type { ColumnsType } from 'antd/es/table'
import {
  getCacheStats, cleanupCache, clearAllCache, getCacheDetails, getCacheBackendInfo,
} from '@/services/api/cache'
import type { CacheStats, CacheDetails, CacheBackendInfo } from '@/services/api/cache'

const { Text, Title } = Typography

interface CacheDetailItem {
  key: string
  name: string
  size?: number
  created_at?: string
  expires_at?: string
  type?: string
}

export default function CacheManagementPage() {
  const [stats, setStats] = useState<CacheStats | null>(null)
  const [backendInfo, setBackendInfo] = useState<CacheBackendInfo | null>(null)
  const [details, setDetails] = useState<CacheDetails | null>(null)
  const [loading, setLoading] = useState(false)
  const [clearing, setClearing] = useState(false)

  const loadStats = useCallback(async () => {
    setLoading(true)
    try {
      const [statsRes, backendRes] = await Promise.all([
        getCacheStats().catch(() => null),
        getCacheBackendInfo().catch(() => null),
      ])
      setStats(statsRes?.data ?? null)
      setBackendInfo(backendRes?.data ?? null)
    } finally {
      setLoading(false)
    }
  }, [])

  useState(() => { loadStats() })

  /** 清理过期缓存 */
  const handleCleanup = async (days: number) => {
    setClearing(true)
    try {
      const res = await cleanupCache(days)
      message.success(res.data.message || `已清理 ${days} 天前的缓存`)
      loadStats()
    } catch {
      message.error('清理失败')
    } finally {
      setClearing(false)
    }
  }

  /** 清空全部缓存 */
  const handleClearAll = async () => {
    setClearing(true)
    try {
      await clearAllCache()
      message.success('所有缓存已清空')
      loadStats()
    } catch {
      message.error('清空失败')
    } finally {
      setClearing(false)
    }
  }

  /** 加载详情 */
  const handleLoadDetails = async (page = 1) => {
    setLoading(true)
    try {
      const res = await getCacheDetails(page, 20)
      setDetails(res.data)
    } catch {
      message.error('获取缓存详情失败')
    } finally {
      setLoading(false)
    }
  }

  const formatSize = (bytes: number) => {
    if (bytes < 1024) return `${bytes} B`
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
    if (bytes < 1024 * 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(1)} MB`
    return `${(bytes / 1024 / 1024 / 1024).toFixed(2)} GB`
  }

  const detailColumns: ColumnsType<CacheDetailItem> = [
    { title: '名称/Key', dataIndex: 'name', width: 250, render: t => <Text code style={{ fontSize: 12 }}>{t}</Text> },
    { title: '大小', dataIndex: 'size', width: 100, render: v => v != null ? formatSize(v) : '-' },
    { title: '类型', dataIndex: 'type', width: 100, render: t => t ? <Tag>{t}</Tag> : '-' },
    { title: '创建时间', dataIndex: 'created_at', width: 170, render: t => t ? new Date(t).toLocaleString() : '-' },
    { title: '过期时间', dataIndex: 'expires_at', width: 170, render: t => t ? new Date(t).toLocaleString() : '-' },
  ]

  return (
    <div>
      <Title level={4} style={{ marginBottom: 20 }}>缓存管理</Title>

      {/* 统计卡片 */}
      <Row gutter={16} style={{ marginBottom: 20 }}>
        <Col span={6}>
          <Card size="small">
            <Statistic
              title="文件总数"
              value={stats?.totalFiles ?? 0}
              prefix={<FileTextOutlined />}
              loading={loading}
            />
          </Card>
        </Col>
        <Col span={6}>
          <Card size="small">
            <Statistic
              title="总大小"
              value={stats?.totalSize ?? 0}
              formatter={(v) => formatSize(Number(v))}
              prefix={<HddOutlined />}
              loading={loading}
            />
          </Card>
        </Col>
        <Col span={6}>
          <Card size="small">
            <Statistic
              title="股票数据"
              value={stats?.stockDataCount ?? 0}
              prefix={<DatabaseOutlined />}
              suffix="条"
              loading={loading}
            />
          </Card>
        </Col>
        <Col span={6}>
          <Card size="small">
            <Statistic
              title="上限"
              value={stats?.maxSize ?? 0}
              formatter={(v) => formatSize(Number(v))}
              loading={loading}
            />
          </Card>
        </Col>
      </Row>

      {/* 后端信息 */}
      {backendInfo && (
        <Card size="small" title="缓存后端信息" style={{ marginBottom: 16 }}>
          <Descriptions size="small" column={3}>
            <Descriptions.Item label="系统">{backendInfo.system}</Descriptions.Item>
            <Descriptions.Item label="主后端">{backendInfo.primary_backend}</Descriptions.Item>
            <Descriptions.Item label="降级启用">
              {backendInfo.fallback_enabled ? <Tag color="success">是</Tag> : <Tag>否</Tag>}
            </Descriptions.Item>
          </Descriptions>
        </Card>
      )}

      {/* 操作按钮 */}
      <Card size="small" style={{ marginBottom: 16 }}>
        <Space wrap>
          <Text strong>缓存操作：</Text>
          <Button icon={<ReloadOutlined />} onClick={loadStats} loading={loading}>刷新统计</Button>
          <Popconfirm title="确定清理 7 天前的缓存？" onConfirm={() => handleCleanup(7)}>
            <Button icon={<DeleteOutlined />} loading={clearing}>清理 7 天前</Button>
          </Popconfirm>
          <Popconfirm title="确定清理 30 天前的缓存？" onConfirm={() => handleCleanup(30)}>
            <Button icon={<DeleteOutlined />} loading={clearing}>清理 30 天前</Button>
          </Popconfirm>
          <Popconfirm
            title="确定清空所有缓存？此操作不可恢复！"
            onConfirm={handleClearAll}
          >
            <Button danger icon={<ClearOutlined />} loading={clearing}>清空全部</Button>
          </Popconfirm>
        </Space>
      </Card>

      {/* 详情表格 */}
      <Card
        size="small"
        title={
          <span>
            缓存详情
            {details && <Tag style={{ marginLeft: 8 }}>共 {details.total} 条</Tag>}
          </span>
        }
        extra={
          <Button size="small" icon={<ReloadOutlined />} onClick={() => handleLoadDetails(1)} loading={loading}>
            刷新
          </Button>
        }
      >
        <Table<CacheDetailItem>
          dataSource={(details?.items as unknown as CacheDetailItem[]) ?? []}
          columns={detailColumns}
          rowKey="name"
          loading={loading}
          pagination={
            details
              ? {
                  current: details.page,
                  pageSize: details.page_size,
                  total: details.total,
                  onChange: (page) => handleLoadDetails(page),
                }
              : false
          }
          size="small"
          locale={{ emptyText: '暂无缓存数据' }}
        />
      </Card>
    </div>
  )
}
