import { Typography, Card, Table, Button, Tag, Space, Popconfirm, Empty } from 'antd'
import { ReloadOutlined, DeleteOutlined, StockOutlined } from '@ant-design/icons'
import { useFavorites } from '@/features/stocks/hooks/useFavorites'
import { getMarketColors } from '@/utils/market'
import type { FavoriteStock } from '@/types/favorites.types'

const { Title, Text } = Typography

export default function FavoritesPage() {
  const { favorites, loading, error, refresh, remove, syncRealtime } = useFavorites()

  const columns = [
    {
      title: '股票',
      dataIndex: 'stock_code',
      render: (_: unknown, record: FavoriteStock) => (
        <Space orientation="vertical" size={0}>
          <Text strong style={{ color: 'var(--text-primary)' }}>{record.stock_name}</Text>
          <Text style={{ color: 'var(--text-secondary)', fontSize: 12 }}>{record.stock_code}</Text>
        </Space>
      ),
    },
    {
      title: '市场',
      dataIndex: 'market',
      render: (market: string) => <Tag color="default">{market}</Tag>,
    },
    {
      title: '最新价',
      dataIndex: 'current_price',
      render: (price: number | null, record: FavoriteStock) => {
        const change = record.change_percent ?? 0
        const colors = getMarketColors(record.market)
        const color = change >= 0 ? colors.up : colors.down
        return (
          <Text strong style={{ color }}>
            {price !== null && price !== undefined ? price.toFixed(2) : '-'}
          </Text>
        )
      },
    },
    {
      title: '涨跌幅',
      dataIndex: 'change_percent',
      render: (change: number | null, record: FavoriteStock) => {
        if (change === null || change === undefined) return '-'
        const colors = getMarketColors(record.market)
        const color = change >= 0 ? colors.up : colors.down
        return (
          <Text style={{ color }}>
            {change >= 0 ? '+' : ''}{change.toFixed(2)}%
          </Text>
        )
      },
    },
    {
      title: '标签',
      dataIndex: 'tags',
      render: (tags: string[]) => (
        <Space wrap>
          {tags?.map((tag) => (
            <Tag key={tag} color="default" style={{ fontSize: 11 }}>{tag}</Tag>
          ))}
        </Space>
      ),
    },
    {
      title: '操作',
      key: 'action',
      render: (_: unknown, record: FavoriteStock) => (
        <Space>
          <Button
            size="small"
            icon={<StockOutlined />}
            href={`/stocks/${encodeURIComponent(record.stock_code)}`}
          >
            详情
          </Button>
          <Popconfirm
            title="确认删除该自选股？"
            onConfirm={async () => {
              const ok = await remove(record.stock_code)
              if (ok) refresh()
            }}
          >
            <Button size="small" danger icon={<DeleteOutlined />}>
              删除
            </Button>
          </Popconfirm>
        </Space>
      ),
    },
  ]

  return (
    <div style={{ color: 'var(--text-primary)' }}>
      <Space style={{ marginBottom: 24, width: '100%', justifyContent: 'space-between' }}>
        <Title level={3} style={{ color: 'var(--text-primary)', margin: 0 }}>我的自选股</Title>
        <Space>
          <Button onClick={syncRealtime} loading={loading}>同步行情</Button>
          <Button icon={<ReloadOutlined />} onClick={refresh} loading={loading}>刷新</Button>
        </Space>
      </Space>

      {error && (
        <div style={{ marginBottom: 16, color: 'var(--accent-error)' }}>{error}</div>
      )}

      <Card style={{ background: 'var(--bg-card)', border: 'none' }}>
        <Table
          dataSource={favorites}
          columns={columns}
          rowKey="stock_code"
          loading={loading && favorites.length === 0}
          pagination={false}
          scroll={{ x: 'max-content' }}
          locale={{
            emptyText: <Empty description="暂无自选股" image={Empty.PRESENTED_IMAGE_SIMPLE} />,
          }}
        />
      </Card>
    </div>
  )
}
