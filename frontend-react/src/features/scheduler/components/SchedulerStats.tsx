/**
 * 调度器统计卡片组件
 * 展示总任务数、运行中、已暂停、今日执行次数、成功率
 */

import { Card, Statistic, Row, Col } from 'antd'
import {
  ScheduleOutlined, PlayCircleOutlined, PauseCircleOutlined,
  ThunderboltOutlined, CheckCircleOutlined,
} from '@ant-design/icons'
import type { SchedulerStats as SchedulerStatsType } from '@/services/api/scheduler'

interface SchedulerStatsProps {
  stats: SchedulerStatsType | null
}

export default function SchedulerStats({ stats }: SchedulerStatsProps) {
  if (!stats) return null

  return (
    <Card size="small">
      <Row gutter={24}>
        <Col span={4}>
          <Statistic
            title="总任务数"
            value={stats.total_jobs}
            prefix={<ScheduleOutlined />}
          />
        </Col>
        <Col span={4}>
          <Statistic
            title="运行中"
            value={stats.active_jobs}
            styles={{ content: { color: '#52C41A' } }}
            prefix={<PlayCircleOutlined />}
          />
        </Col>
        <Col span={4}>
          <Statistic
            title="已暂停"
            value={stats.paused_jobs}
            styles={{ content: { color: '#D48806' } }}
            prefix={<PauseCircleOutlined />}
          />
        </Col>
        <Col span={5}>
          <Statistic
            title="今日执行"
            value={stats.today_executions}
            prefix={<ThunderboltOutlined />}
          />
        </Col>
        <Col span={7}>
          <Statistic
            title="成功率"
            value={stats.success_rate}
            precision={1}
            suffix="%"
            styles={{ content: {
              color: stats.success_rate >= 80 ? '#52C41A' : stats.success_rate >= 50 ? '#D48806' : '#FF4D4F',
            } }}
            prefix={<CheckCircleOutlined />}
          />
        </Col>
      </Row>
    </Card>
  )
}
