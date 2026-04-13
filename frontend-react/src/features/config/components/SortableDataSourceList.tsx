/**
 * 可排序的数据源列表
 * 在指定市场分类下展示关联的数据源，支持拖拽调整优先级、启用/禁用切换
 */

import { useState, useCallback, useEffect, useRef } from 'react'
import {
  Table, Button, Switch, Space, Tag, message, Typography, Card, Empty,
} from 'antd'
import {
  ArrowUpOutlined, ArrowDownOutlined, ReloadOutlined,
} from '@ant-design/icons'
import type { ColumnsType } from 'antd/es/table'
import type { DataSourceConfig, DataSourceGrouping, MarketCategory } from '@/types/config.types'
import {
  getDataSourceGroupings, updateDataSourceGrouping, updateCategoryDatasourceOrder,
  getDataSourceConfigs,
} from '@/services/api/config'

const { Text } = Typography

interface SortableDataSourceListProps {
  category: MarketCategory | null
  onRefresh?: () => void
}

export default function SortableDataSourceList({ category, onRefresh }: SortableDataSourceListProps) {
  const [groupings, setGroupings] = useState<DataSourceGrouping[]>([])
  const [dataSources, setDataSources] = useState<DataSourceConfig[]>([])
  const [loading, setLoading] = useState(false)

  const loadData = useCallback(async () => {
    if (!category) return
    setLoading(true)
    try {
      const [grpRes, dsRes] = await Promise.all([
        getDataSourceGroupings(),
        getDataSourceConfigs(),
      ])
      setGroupings(grpRes.data ?? [])
      setDataSources(dsRes.data ?? [])
    } catch {
      // 静默
    } finally {
      setLoading(false)
    }
  }, [category])

  const initializedRef = useRef(false)
  useEffect(() => {
    if (!category) return
    if (initializedRef.current) {
      loadData()
      return
    }
    initializedRef.current = true
    loadData()
  }, [category, loadData])

  /** 获取当前分类的分组关系（按 priority 排序） */
  const currentGroupings = category
    ? groupings
        .filter(g => g.market_category_id === category.id)
        .sort((a, b) => a.priority - b.priority)
    : []

  /** 获取数据源详情 */
  const getDataSourceDetail = (name: string): DataSourceConfig | undefined => {
    return dataSources.find(ds => ds.name === name)
  }

  /** 上移/下移调整优先级 */
  const movePriority = async (index: number, direction: 'up' | 'down') => {
    if (!category) return
    const newOrder = [...currentGroupings]
    const targetIndex = direction === 'up' ? index - 1 : index + 1
    if (targetIndex < 0 || targetIndex >= newOrder.length) return

    // 交换 priority 值
    const temp = newOrder[index].priority
    newOrder[index].priority = newOrder[targetIndex].priority
    newOrder[targetIndex].priority = temp

    // 同时交换位置
    ;[newOrder[index], newOrder[targetIndex]] = [newOrder[targetIndex], newOrder[index]]

    try {
      await updateCategoryDatasourceOrder(category.id, newOrder.map((g, i) => ({ name: g.data_source_name, priority: i })))
      message.success('排序已更新')
      loadData()
      onRefresh?.()
    } catch {
      message.error('排序更新失败')
    }
  }

  /** 切换启用/禁用 */
  const toggleEnabled = async (g: DataSourceGrouping) => {
    try {
      await updateDataSourceGrouping(g.data_source_name, g.market_category_id, { enabled: !g.enabled })
      message.success(`已${!g.enabled ? '启用' : '禁用'}`)
      loadData()
      onRefresh?.()
    } catch {
      message.error('操作失败')
    }
  }

  const columns: ColumnsType<DataSourceGrouping & { index: number }> = [
    {
      title: '#',
      width: 50,
      render: (_, __, i) => (
        <Space size={2}>
          <Button
            size="small"
            type="text"
            icon={<ArrowUpOutlined />}
            disabled={i === 0}
            onClick={() => movePriority(i, 'up')}
          />
          <Button
            size="small"
            type="text"
            icon={<ArrowDownOutlined />}
            disabled={i === currentGroupings.length - 1}
            onClick={() => movePriority(i, 'down')}
          />
        </Space>
      ),
    },
    {
      title: '数据源',
      dataIndex: 'data_source_name',
      width: 180,
      render: (name) => {
        const ds = getDataSourceDetail(name)
        return (
          <span>
            <Text strong>{ds?.display_name || name}</Text>
            {ds?.type && <Tag style={{ marginLeft: 6 }} color="blue">{ds.type}</Tag>}
          </span>
        )
      },
    },
    {
      title: '优先级',
      dataIndex: 'priority',
      width: 70,
      sorter: (a, b) => a.priority - b.priority,
    },
    {
      title: '状态',
      width: 90,
      dataIndex: 'enabled',
      render: (enabled, record) => (
        <Switch
          size="small"
          checked={enabled}
          onChange={() => toggleEnabled(record)}
          checkedChildren="启用"
          unCheckedChildren="禁用"
        />
      ),
    },
  ]

  if (!category) {
    return (
      <Card size="small">
        <Empty description="请在左侧选择一个市场分类查看其数据源" />
      </Card>
    )
  }

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
        <Text strong>
          「{category.display_name}」的数据源优先级
          <Tag style={{ marginLeft: 8 }}>{currentGroupings.length} 个</Tag>
        </Text>
        <Button size="small" icon={<ReloadOutlined />} onClick={loadData} loading={loading}>
          刷新
        </Button>
      </div>

      <Table
        dataSource={currentGroupings.map((g, i) => ({ ...g, index: i }))}
        columns={columns}
        rowKey="data_source_name"
        loading={loading}
        pagination={false}
        size="small"
        locale={{ emptyText: `「${category.display_name}」下暂无关联数据源` }}
      />
    </div>
  )
}
