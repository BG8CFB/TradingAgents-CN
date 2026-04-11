import type { ReactNode } from 'react'

interface AuthLayoutProps {
  children: ReactNode
}

export default function AuthLayout({ children }: AuthLayoutProps) {
  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        minHeight: '100vh',
        background: 'var(--bg-base)',
        padding: 24,
      }}
    >
      <div
        style={{
          width: '100%',
          maxWidth: 420,
          padding: '40px 32px',
          background: 'var(--bg-card)',
          borderRadius: 16,
          border: '1px solid var(--border-color)',
          boxShadow: '0 4px 24px rgba(201, 169, 110, 0.08), 0 1px 4px rgba(0, 0, 0, 0.04)',
        }}
      >
        <div style={{ textAlign: 'center', marginBottom: 32 }}>
          <h1
            style={{
              fontSize: 28,
              fontWeight: 700,
              color: 'var(--accent-primary)',
              marginBottom: 8,
              letterSpacing: 1,
            }}
          >
            TradingAgents
          </h1>
          <p style={{ color: 'var(--text-secondary)', fontSize: 14 }}>
            智能股票分析平台
          </p>
        </div>
        {children}
      </div>
    </div>
  )
}
