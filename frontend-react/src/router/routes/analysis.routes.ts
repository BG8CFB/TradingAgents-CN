import type { RouteObject } from 'react-router-dom'

export const analysisRoutes: RouteObject[] = [
  {
    path: '/analysis/single',
    lazy: async () => {
      const { default: SingleAnalysisPage } = await import('@/pages/analysis/SingleAnalysisPage')
      return { Component: SingleAnalysisPage }
    },
  },
  {
    path: '/analysis/batch',
    lazy: async () => {
      const { default: BatchAnalysisPage } = await import('@/pages/analysis/BatchAnalysisPage')
      return { Component: BatchAnalysisPage }
    },
  },
]
