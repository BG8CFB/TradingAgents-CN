import { useEffect, useState } from 'react'
import { Card, Typography, Tag, Empty, Spin, Space, Button } from 'antd'
import { useNavigate } from 'react-router-dom'
import { getReportList, type ReportItem } from '@/services/api/reports'

const { Text } = Typography

export default function RecentAnalysesCard() {
  const navigate = useNavigate()
  const [reports, setReports] = useState<ReportItem[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    getReportList({ page: 1, page_size: 5 }, { skipErrorHandler: true })
      .then((res) => {
        setReports(res.data?.reports ?? [])
      })
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [])

  return (
    <Card
      title={
        <span style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <span style={{ color: 'var(--text-primary)' }}>最近分析</span>
          <Text
            type="secondary"
            style={{ fontSize: 12, cursor: 'pointer', color: 'var(--accent-blue)' }}
            onClick={() => navigate('/reports')}
          >
            查看全部 →
          </Text>
        </span>
      }
      style={{ background: 'var(--bg-card)', border: 'none' }}
      styles={{ header: { borderBottom: '1px solid var(--border-color)' } }}
    >
      <Spin spinning={loading}>
        {reports.length === 0 ? (
          <Empty
            description="暂无分析记录"
            image={Empty.PRESENTED_IMAGE_SIMPLE}
          >
            <Button type="primary" size="small" onClick={() => navigate('/analysis/single')}>
              开始单股分析
            </Button>
          </Empty>
        ) : (
          <div>
            {reports.map((item) => (
              <div
                key={item.id}
                style={{ cursor: 'pointer', padding: '10px 0', borderBottom: '1px solid var(--border-color)' }}
                onClick={() => navigate(`/reports/view?id=${item.id}`)}
              >
                <div style={{ marginBottom: 4 }}>
                  <span style={{ color: 'var(--text-primary)', fontSize: 13 }}>{item.title}</span>
                </div>
                <Space size={8}>
                  <Tag color={item.status === 'completed' ? 'success' : 'processing'} style={{ fontSize: 11 }}>
                    {item.status === 'completed' ? '已完成' : '进行中'}
                  </Tag>
                  <Text type="secondary" style={{ fontSize: 11 }}>
                    {item.market_type} · {item.created_at?.slice(0, 10)}
                  </Text>
                </Space>
              </div>
            ))}
          </div>
        )}
      </Spin>
    </Card>
  )
}
