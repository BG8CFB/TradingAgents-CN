import { Card, Row, Col, Statistic, Tag, Space, Typography } from 'antd'
import { RiseOutlined, FallOutlined } from '@ant-design/icons'
import type { StockQuote, StockFundamentals } from '@/types/stocks.types'
import { getMarketColors } from '@/utils/market'

const { Text } = Typography

interface StockQuoteCardProps {
  quote?: StockQuote | null
  fundamentals?: StockFundamentals | null
  loading?: boolean
}

export default function StockQuoteCard({ quote, fundamentals, loading }: StockQuoteCardProps) {
  if (loading || !quote) {
    return (
      <Card style={{ background: 'var(--bg-card)', border: 'none' }}>
        <div style={{ height: 120, display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--text-secondary)' }}>
          加载行情中...
        </div>
      </Card>
    )
  }

  const price = quote.price ?? 0
  const change = quote.change_percent ?? 0
  const name = quote.name || fundamentals?.name || quote.code
  const market = quote.market || fundamentals?.market || 'CN'
  const colors = getMarketColors(market)
  const color = change >= 0 ? colors.up : colors.down

  return (
    <Card
      style={{ background: 'var(--bg-card)', border: 'none' }}
      styles={{ body: { padding: 20 } }}
    >
      <Row gutter={[24, 16]} align="middle">
        <Col xs={24} md={8}>
          <Space orientation="vertical" size={4}>
            <Text strong style={{ color: 'var(--text-primary)', fontSize: 20 }}>
              {name}
            </Text>
            <Space>
              <Tag color="default">{quote.code}</Tag>
              <Tag color="default">{market}</Tag>
            </Space>
          </Space>
        </Col>

        <Col xs={24} md={8}>
          <Space align="baseline">
            <Text strong style={{ color, fontSize: 32 }}>
              {price.toFixed(2)}
            </Text>
            <Text style={{ color, fontSize: 16 }}>
              {change >= 0 ? '+' : ''}
              {change.toFixed(2)}%
            </Text>
            {change >= 0 ? (
              <RiseOutlined style={{ color, fontSize: 18 }} />
            ) : (
              <FallOutlined style={{ color, fontSize: 18 }} />
            )}
          </Space>
        </Col>

        <Col xs={24} md={8}>
          <Row gutter={[16, 8]}>
            <Col span={12}>
              <Statistic
                title={<Text style={{ color: 'var(--text-secondary)', fontSize: 12 }}>成交量</Text>}
                value={quote.volume ?? 0}
                styles={{ content: { color: 'var(--text-primary)', fontSize: 14, fontWeight: 500 } }}
                formatter={(v) => formatVolume(Number(v))}
              />
            </Col>
            <Col span={12}>
              <Statistic
                title={<Text style={{ color: 'var(--text-secondary)', fontSize: 12 }}>成交额</Text>}
                value={quote.amount ?? 0}
                styles={{ content: { color: 'var(--text-primary)', fontSize: 14, fontWeight: 500 } }}
                formatter={(v) => formatAmount(Number(v))}
              />
            </Col>
            <Col span={12}>
              <Statistic
                title={<Text style={{ color: 'var(--text-secondary)', fontSize: 12 }}>换手率</Text>}
                value={quote.turnover_rate ?? '-'}
                suffix="%"
                styles={{ content: { color: 'var(--text-primary)', fontSize: 14, fontWeight: 500 } }}
              />
            </Col>
            <Col span={12}>
              <Statistic
                title={<Text style={{ color: 'var(--text-secondary)', fontSize: 12 }}>振幅</Text>}
                value={quote.amplitude ?? '-'}
                suffix="%"
                styles={{ content: { color: 'var(--text-primary)', fontSize: 14, fontWeight: 500 } }}
              />
            </Col>
          </Row>
        </Col>
      </Row>
    </Card>
  )
}

function formatVolume(n: number): string {
  if (n >= 1e8) return (n / 1e8).toFixed(2) + '亿'
  if (n >= 1e4) return (n / 1e4).toFixed(2) + '万'
  return n.toLocaleString()
}

function formatAmount(n: number): string {
  if (n >= 1e8) return (n / 1e8).toFixed(2) + '亿'
  if (n >= 1e4) return (n / 1e4).toFixed(2) + '万'
  return n.toLocaleString()
}
