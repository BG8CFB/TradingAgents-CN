import type { ReactNode } from 'react'
import { Layout } from 'antd'
import { Outlet } from 'react-router-dom'
import Sidebar from './Sidebar'
import Header from './Header'
import Footer from './Footer'

const { Content } = Layout

interface AppLayoutProps {
  children?: ReactNode
}

export default function AppLayout({ children }: AppLayoutProps) {
  return (
    <Layout style={{ minHeight: '100vh', background: 'var(--bg-base)' }}>
      <Sidebar />
      <Layout style={{ background: 'transparent' }}>
        <Header />
        <Content
          style={{
            margin: '24px',
            padding: 0,
            background: 'transparent',
            minHeight: 280,
            color: 'var(--text-primary)',
          }}
        >
          {children ?? <Outlet />}
        </Content>
        <Footer />
      </Layout>
    </Layout>
  )
}
