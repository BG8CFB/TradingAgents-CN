import type { RouteObject } from 'react-router-dom'

export const settingsRoutes: RouteObject[] = [
  {
    path: '/settings/profile',
    lazy: async () => {
      const { default: SettingsPage } = await import('@/pages/settings/SettingsPage')
      return { Component: SettingsPage }
    },
  },
  {
    path: '/settings/config',
    lazy: async () => {
      const { default: ConfigManagementPage } = await import('@/pages/settings/ConfigManagementPage')
      return { Component: ConfigManagementPage }
    },
  },
  {
    path: '/settings/mcp',
    lazy: async () => {
      const { default: MCPManagementPage } = await import('@/pages/settings/MCPManagementPage')
      return { Component: MCPManagementPage }
    },
  },
  {
    path: '/settings/mcp-tools',
    lazy: async () => {
      const { default: MCPToolsPage } = await import('@/pages/settings/MCPToolsPage')
      return { Component: MCPToolsPage }
    },
  },
  {
    path: '/settings/agents',
    lazy: async () => {
      const { default: AgentManagementPage } = await import('@/pages/settings/AgentManagementPage')
      return { Component: AgentManagementPage }
    },
  },
  {
    path: '/settings/cache',
    lazy: async () => {
      const { default: CacheManagementPage } = await import('@/pages/settings/CacheManagementPage')
      return { Component: CacheManagementPage }
    },
  },
  {
    path: '/settings/usage',
    lazy: async () => {
      const { default: UsageStatisticsPage } = await import('@/pages/settings/UsageStatisticsPage')
      return { Component: UsageStatisticsPage }
    },
  },
]
