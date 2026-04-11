import type { RouteObject } from 'react-router-dom'

export const authRoutes: RouteObject[] = [
  {
    path: '/login',
    lazy: async () => {
      const { default: LoginPage } = await import('@/pages/auth/LoginPage')
      return { Component: LoginPage }
    },
  },
]
