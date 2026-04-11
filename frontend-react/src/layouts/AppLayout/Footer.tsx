import { Layout } from 'antd'

const { Footer: AntFooter } = Layout

export default function Footer() {
  return (
    <AntFooter
      style={{
        textAlign: 'center',
        background: 'transparent',
        color: 'var(--text-muted)',
        fontSize: 12,
        padding: '16px 24px',
      }}
    >
      TradingAgents ©{new Date().getFullYear()} - 智能股票分析平台
    </AntFooter>
  )
}
