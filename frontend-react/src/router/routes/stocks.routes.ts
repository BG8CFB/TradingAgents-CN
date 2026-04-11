import type { RouteObject } from 'react-router-dom'

export const stocksRoutes: RouteObject[] = [
  {
    path: '/stocks/:code',
    lazy: async () => {
      const { default: StockDetailPage } = await import('@/pages/stocks/StockDetailPage')
      return { Component: StockDetailPage }
    },
  },
  {
    path: '/screening',
    lazy: async () => {
      const { default: ScreeningPage } = await import('@/pages/screening/ScreeningPage')
      return { Component: ScreeningPage }
    },
  },
  {
    path: '/favorites',
    lazy: async () => {
      const { default: FavoritesPage } = await import('@/pages/favorites/FavoritesPage')
      return { Component: FavoritesPage }
    },
  },
]
