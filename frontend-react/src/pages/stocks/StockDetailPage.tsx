import { useParams } from 'react-router-dom'
import { Typography, Row, Col, Button, Space } from 'antd'
import { ReloadOutlined } from '@ant-design/icons'
import { useStockQuote } from '@/features/stocks/hooks/useStockQuote'
import StockQuoteCard from '@/features/stocks/components/StockQuoteCard'
import KlineChart from '@/features/stocks/components/KlineChart'
import FundamentalsTable from '@/features/stocks/components/FundamentalsTable'
import NewsList from '@/features/stocks/components/NewsList'
import FavoriteButton from '@/features/stocks/components/FavoriteButton'

const { Title } = Typography

export default function StockDetailPage() {
  const { code } = useParams<{ code: string }>()
  const symbol = decodeURIComponent(code || '')

  const { quote, fundamentals, loading, error, refresh } = useStockQuote(symbol)

  return (
    <div style={{ color: 'var(--text-primary)' }}>
      <Space style={{ marginBottom: 24, width: '100%', justifyContent: 'space-between' }}>
        <Title level={3} style={{ color: 'var(--text-primary)', margin: 0 }}>
          股票详情
        </Title>
        <Space>
          <FavoriteButton stockCode={symbol} stockName={quote?.name} market={quote?.market} />
          <Button icon={<ReloadOutlined />} onClick={refresh} loading={loading}>
            刷新
          </Button>
        </Space>
      </Space>

      {error && (
        <div style={{ marginBottom: 16, color: 'var(--accent-error)' }}>{error}</div>
      )}

      <Row gutter={[24, 24]}>
        <Col xs={24}>
          <StockQuoteCard quote={quote} fundamentals={fundamentals} loading={loading} />
        </Col>

        <Col xs={24} lg={16}>
          <KlineChart code={symbol} height={400} />
        </Col>

        <Col xs={24} lg={8}>
          <FundamentalsTable data={fundamentals} loading={loading} />
        </Col>

        <Col xs={24}>
          <NewsList code={symbol} />
        </Col>
      </Row>
    </div>
  )
}
