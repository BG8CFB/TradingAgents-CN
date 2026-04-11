import { Card, Typography, Space } from 'antd'
import { UserOutlined } from '@ant-design/icons'
import { useAuthStore } from '@/stores/auth.store'

const { Title, Paragraph } = Typography

export default function WelcomeSection() {
  const user = useAuthStore((s) => s.user)
  const hour = new Date().getHours()
  const greeting = hour < 6 ? '夜深了' : hour < 12 ? '早上好' : hour < 14 ? '中午好' : hour < 18 ? '下午好' : '晚上好'

  return (
    <Card style={{ background: 'var(--bg-card)', border: 'none' }} styles={{ body: { padding: '24px 28px' } }}>
      <Space size="large" align="center">
        <div
          style={{
            width: 52,
            height: 52,
            borderRadius: '50%',
            background: 'linear-gradient(135deg, #C9A96E, #D4A574)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            color: '#FFF',
            fontSize: 22,
          }}
        >
          <UserOutlined />
        </div>
        <div>
          <Title level={4} style={{ margin: 0, color: 'var(--text-primary)' }}>
            {greeting}，{user?.username || '用户'}
          </Title>
          <Paragraph style={{ margin: '4px 0 0', color: 'var(--text-secondary)', fontSize: 13 }}>
            欢迎使用 TradingAgents 智能股票分析平台
          </Paragraph>
        </div>
      </Space>
    </Card>
  )
}
