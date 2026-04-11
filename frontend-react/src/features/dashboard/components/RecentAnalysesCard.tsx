import { useEffect, useState } from 'react'
import { Card, Typography, List, Tag, Empty, Spin, Space } from 'antd'
import { useNavigate } from 'react-router-dom'
import { getReportList, type ReportItem } from '@/services/api/reports'

const { Text } = Typography

export default function RecentAnalysesCard() {
  const navigate = useNavigate()
  const [reports, setReports] = useState<ReportItem[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    getReportList({ page: 1, page_size: 5 })
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
          <Empty description="暂无分析记录" image={Empty.PRESENTED_IMAGE_SIMPLE} />
        ) : (
          <List
            dataSource={reports}
            renderItem={(item) => (
              <List.Item
                style={{ cursor: 'pointer', padding: '10px 0', borderBottom: '1px solid var(--border-color)' }}
                onClick={() => navigate(`/reports/view?id=${item.id}`)}
              >
                <List.Item.Meta
                  title={
                    <span style={{ color: 'var(--text-primary)', fontSize: 13 }}>{item.title}</span>
                  }
                  description={
                    <Space size={8}>
                      <Tag color={item.status === 'completed' ? 'success' : 'processing'} style={{ fontSize: 11 }}>
                        {item.status === 'completed' ? '已完成' : '进行中'}
                      </Tag>
                      <Text type="secondary" style={{ fontSize: 11 }}>
                        {item.market_type} · {item.created_at?.slice(0, 10)}
                      </Text>
                    </Space>
                  }
                />
              </List.Item>
            )}
          />
        )}
      </Spin>
    </Card>
  )
}
