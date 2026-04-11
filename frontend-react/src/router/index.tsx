/* eslint-disable react-refresh/only-export-components */
import { createBrowserRouter, Navigate, Outlet, type RouteObject } from 'react-router-dom'
import { Suspense } from 'react'
import { Spin } from 'antd'
import AppLayout from '@/layouts/AppLayout'
import AuthLayout from '@/layouts/AuthLayout'
import { checkAuth } from './guards'
import { useAuthStore } from '@/stores/auth.store'
import { authRoutes } from './routes/auth.routes'
import { analysisRoutes } from './routes/analysis.routes'
import { stocksRoutes } from './routes/stocks.routes'
import { settingsRoutes } from './routes/settings.routes'
import { systemRoutes } from './routes/system.routes'

// 占位符页面（用于懒加载前显示）
function PageLoading() {
  return (
    <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: '100vh' }}>
      <Spin size="large" />
    </div>
  )
}

// 认证布局包装
function AuthRoot() {
  return (
    <AuthLayout>
      <Suspense fallback={<PageLoading />}>
        <Outlet />
      </Suspense>
    </AuthLayout>
  )
}

// 受保护布局包装
function ProtectedRoot() {
  const hasRehydrated = useAuthStore((state) => state.hasRehydrated)
  const isAuthenticated = useAuthStore((state) => state.isAuthenticated)
  if (!hasRehydrated) {
    return <PageLoading />
  }
  if (!isAuthenticated || !checkAuth()) {
    return <Navigate to="/login" replace />
  }
  return (
    <AppLayout>
      <Suspense fallback={<PageLoading />}>
        <Outlet />
      </Suspense>
    </AppLayout>
  )
}

// 公共布局包装（可选鉴权，如仪表盘可匿名查看）
function MainRoot() {
  return (
    <AppLayout>
      <Suspense fallback={<PageLoading />}>
        <Outlet />
      </Suspense>
    </AppLayout>
  )
}

const routes: RouteObject[] = [
  // 认证相关
  {
    element: <AuthRoot />,
    children: authRoutes,
  },

  // 主应用（受保护）
  {
    element: <ProtectedRoot />,
    children: [
      {
        index: true,
        element: <Navigate to="/dashboard" replace />,
      },
      {
        path: '/dashboard',
        lazy: async () => {
          const { default: DashboardPage } = await import('@/pages/dashboard/DashboardPage')
          return { Component: DashboardPage }
        },
      },
      {
        path: '/tasks',
        lazy: async () => {
          const { default: TaskCenterPage } = await import('@/pages/tasks/TaskCenterPage')
          return { Component: TaskCenterPage }
        },
      },
      {
        path: '/reports',
        lazy: async () => {
          const { default: ReportListPage } = await import('@/pages/reports/ReportListPage')
          return { Component: ReportListPage }
        },
      },
      {
        path: '/reports/view/:id',
        lazy: async () => {
          const { default: ReportDetailPage } = await import('@/pages/reports/ReportDetailPage')
          return { Component: ReportDetailPage }
        },
      },
      {
        path: '/reports/token',
        lazy: async () => {
          const { default: TokenStatisticsPage } = await import('@/pages/reports/TokenStatisticsPage')
          return { Component: TokenStatisticsPage }
        },
      },
      ...analysisRoutes,
      ...stocksRoutes,
      ...settingsRoutes,
      ...systemRoutes,
    ],
  },

  // 学习中心（公开访问）
  {
    element: <MainRoot />,
    children: [
      {
        path: '/learning',
        lazy: async () => {
          const { default: LearningIndexPage } = await import('@/pages/learning/LearningIndexPage')
          return { Component: LearningIndexPage }
        },
      },
    ],
  },

  // 404
  {
    path: '*',
    lazy: async () => {
      const { default: NotFoundPage } = await import('@/pages/errors/NotFoundPage')
      return { Component: NotFoundPage }
    },
  },
]

export const router = createBrowserRouter(routes)

export default router
