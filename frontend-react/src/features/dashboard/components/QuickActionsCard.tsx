import { Card, Typography, Row, Col, Button } from 'antd'
import { useNavigate } from 'react-router-dom'
import {
  LineChartOutlined,
  SearchOutlined,
  StarOutlined,
  FileTextOutlined,
} from '@ant-design/icons'

const {} = Typography

interface ActionItem {
  icon: React.ReactNode
  label: string
  desc: string
  path: string
}

const actions: ActionItem[] = [
  { icon: <LineChartOutlined />, label: '单股分析', desc: '深度分析个股', path: '/analysis/single' },
  { icon: <LineChartOutlined />, label: '批量分析', desc: '多股票批量处理', path: '/analysis/batch' },
  { icon: <SearchOutlined />, label: '智能筛选', desc: '条件选股', path: '/screening' },
  { icon: <StarOutlined />, label: '我的自选', desc: '收藏管理', path: '/favorites' },
  { icon: <FileTextOutlined />, label: '分析报告', desc: '历史报告查看', path: '/reports' },
]

export default function QuickActionsCard() {
  const navigate = useNavigate()

  return (
    <Card
      title={<span style={{ color: 'var(--text-primary)' }}>快捷操作</span>}
      style={{ background: 'var(--bg-card)', border: 'none' }}
      styles={{ header: { borderBottom: '1px solid var(--border-color)' } }}
    >
      <Row gutter={[16, 16]}>
        {actions.map((item) => (
          <Col xs={12} sm={8} md={4} key={item.path}>
            <Button
              block
              size="large"
              onClick={() => navigate(item.path)}
              style={{
                height: 80,
                display: 'flex',
                flexDirection: 'column',
                alignItems: 'center',
                justifyContent: 'center',
                gap: 8,
                background: 'var(--bg-base)',
                borderColor: 'var(--border-color)',
                color: 'var(--text-primary)',
              }}
            >
              <span style={{ fontSize: 22, color: 'var(--accent-primary)' }}>{item.icon}</span>
              <span style={{ fontWeight: 500 }}>{item.label}</span>
              <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>{item.desc}</span>
            </Button>
          </Col>
        ))}
      </Row>
    </Card>
  )
}
