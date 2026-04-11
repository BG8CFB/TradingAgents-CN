import type { RouteObject } from 'react-router-dom'

export const systemRoutes: RouteObject[] = [
  {
    path: '/system/database',
    lazy: async () => {
      const { default: DatabaseManagementPage } = await import('@/pages/system/DatabaseManagementPage')
      return { Component: DatabaseManagementPage }
    },
  },
  {
    path: '/system/sync',
    lazy: async () => {
      const { default: SyncManagementPage } = await import('@/pages/system/SyncManagementPage')
      return { Component: SyncManagementPage }
    },
  },
  {
    path: '/system/scheduler',
    lazy: async () => {
      const { default: SchedulerPage } = await import('@/pages/system/SchedulerPage')
      return { Component: SchedulerPage }
    },
  },
  {
    path: '/system/operation-logs',
    lazy: async () => {
      const { default: OperationLogsPage } = await import('@/pages/system/OperationLogsPage')
      return { Component: OperationLogsPage }
    },
  },
  {
    path: '/system/system-logs',
    lazy: async () => {
      const { default: SystemLogsPage } = await import('@/pages/system/SystemLogsPage')
      return { Component: SystemLogsPage }
    },
  },
]
