import { Row, Col } from 'antd'
import WelcomeSection from '@/features/dashboard/components/WelcomeSection'
import QuickActionsCard from '@/features/dashboard/components/QuickActionsCard'
import RecentAnalysesCard from '@/features/dashboard/components/RecentAnalysesCard'
import SystemStatusCard from '@/features/dashboard/components/SystemStatusCard'

export default function DashboardPage() {
  return (
    <div style={{ padding: '0 4px' }}>
      {/* 欢迎区域 */}
      <div style={{ marginBottom: 16 }}>
        <WelcomeSection />
      </div>

      {/* 快捷操作 + 最近分析 */}
      <Row gutter={[16, 16]} style={{ marginBottom: 16 }}>
        <Col xs={24} lg={14}>
          <QuickActionsCard />
        </Col>
        <Col xs={24} lg={10}>
          <RecentAnalysesCard />
        </Col>
      </Row>

      {/* 系统状态 */}
      <div style={{ marginBottom: 16 }}>
        <SystemStatusCard />
      </div>
    </div>
  )
}
