import { create } from 'zustand'
import { persist } from 'zustand/middleware'

type Theme = 'light' | 'dark' | 'auto'
type Language = 'zh-CN' | 'en-US'

interface AppState {
  sidebarCollapsed: boolean
  theme: Theme
  language: Language
  networkStatus: 'online' | 'offline'
  apiStatus: 'connected' | 'disconnected' | 'checking'
  isLoading: boolean
}

interface AppActions {
  toggleSidebar: () => void
  setSidebarCollapsed: (collapsed: boolean) => void
  setTheme: (theme: Theme) => void
  setLanguage: (language: Language) => void
  setNetworkStatus: (status: 'online' | 'offline') => void
  setApiStatus: (status: 'connected' | 'disconnected' | 'checking') => void
  setLoading: (loading: boolean) => void
}

type AppStore = AppState & AppActions

export const useAppStore = create<AppStore>()(
  persist(
    (set) => ({
      sidebarCollapsed: false,
      theme: 'light',
      language: 'zh-CN',
      networkStatus: 'online',
      apiStatus: 'checking',
      isLoading: false,

      toggleSidebar: () =>
        set((state) => ({ sidebarCollapsed: !state.sidebarCollapsed })),

      setSidebarCollapsed: (collapsed) =>
        set({ sidebarCollapsed: collapsed }),

      setTheme: (theme) => set({ theme }),

      setLanguage: (language) => set({ language }),

      setNetworkStatus: (networkStatus) => set({ networkStatus }),

      setApiStatus: (apiStatus) => set({ apiStatus }),

      setLoading: (isLoading) => set({ isLoading }),
    }),
    {
      name: 'app-store',
      partialize: (state) => ({
        sidebarCollapsed: state.sidebarCollapsed,
        theme: state.theme,
        language: state.language,
      }),
    }
  )
)

/**
 * 获取实际主题（处理 auto）
 */
export function getEffectiveTheme(theme: Theme): 'light' | 'dark' {
  if (theme === 'auto') {
    return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
  }
  return theme
}
