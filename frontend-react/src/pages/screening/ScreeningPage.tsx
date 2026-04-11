import { useState } from 'react'
import { Typography, Button, Space, Card, Spin, Pagination, Segmented } from 'antd'
import { SearchOutlined, ReloadOutlined } from '@ant-design/icons'
import { useScreening } from '@/features/screening/hooks/useScreening'
import ConditionBuilder from '@/features/screening/components/ConditionBuilder'
import ScreeningResultTable from '@/features/screening/components/ScreeningResultTable'
import type { ScreeningConditionChild } from '@/types/screening.types'

const { Title, Text } = Typography

const PAGE_SIZE_OPTIONS = [20, 50, 100]

export default function ScreeningPage() {
  const { fields, industries, loading, screening, error, result, run } = useScreening()
  const [conditions, setConditions] = useState<ScreeningConditionChild[]>([])
  const [market, setMarket] = useState<string>('CN')
  const [pageSize, setPageSize] = useState<number>(50)
  const [currentPage, setCurrentPage] = useState<number>(1)

  const handleRun = () => {
    const offset = (currentPage - 1) * pageSize
    run(conditions, market, pageSize, offset)
  }

  const handlePageChange = (page: number, size: number) => {
    setCurrentPage(page)
    setPageSize(size)
    const offset = (page - 1) * size
    run(conditions, market, size, offset)
  }

  return (
    <div style={{ color: 'var(--text-primary)' }}>
      <Space style={{ marginBottom: 24, width: '100%', justifyContent: 'space-between' }}>
        <Title level={3} style={{ color: 'var(--text-primary)', margin: 0 }}>智能筛选</Title>
        <Space>
          <Segmented
            value={market}
            onChange={(v) => setMarket(v as string)}
            options={[
              { label: 'A股', value: 'CN' },
              { label: '美股', value: 'US' },
              { label: '港股', value: 'HK' },
            ]}
          />
          <Button
            type="primary"
            icon={<SearchOutlined />}
            loading={screening}
            onClick={handleRun}
            disabled={conditions.length === 0}
          >
            执行筛选
          </Button>
          <Button icon={<ReloadOutlined />} onClick={handleRun} loading={screening}>
            刷新
          </Button>
        </Space>
      </Space>

      {loading && !screening ? (
        <div style={{ padding: 24, textAlign: 'center' }}>
          <Spin size="large" />
        </div>
      ) : (
        <Card
          title="筛选条件"
          styles={{ header: { color: 'var(--text-primary)', borderBottom: '1px solid rgba(255,255,255,0.06)' } }}
          style={{ background: 'var(--bg-card)', border: 'none', marginBottom: 24 }}
        >
          <ConditionBuilder
            fields={fields}
            industries={industries.map((i) => ({ value: i.value, label: i.label }))}
            value={conditions}
            onChange={setConditions}
            disabled={screening}
          />
        </Card>
      )}

      {error && (
        <div style={{ marginBottom: 16, color: 'var(--accent-error)', padding: 12, background: 'rgba(239,68,68,0.08)', borderRadius: 8 }}>
          {error}
        </div>
      )}

      <Card
        title="筛选结果"
        styles={{ header: { color: 'var(--text-primary)', borderBottom: '1px solid rgba(255,255,255,0.06)' } }}
        style={{ background: 'var(--bg-card)', border: 'none' }}
      >
        <ScreeningResultTable data={result} loading={screening} fields={fields} />

        {result && result.items.length > 0 && (
          <div style={{ marginTop: 16, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <Text style={{ color: 'var(--text-secondary)' }}>
              共找到 <span style={{ color: 'var(--accent-secondary)', fontWeight: 600 }}>{result.total}</span> 条结果
            </Text>
            <Pagination
              current={currentPage}
              pageSize={pageSize}
              total={result.total}
              showSizeChanger
              pageSizeOptions={PAGE_SIZE_OPTIONS}
              onChange={handlePageChange}
              showTotal={(total) => `共 ${total} 条`}
            />
          </div>
        )}
      </Card>
    </div>
  )
}
