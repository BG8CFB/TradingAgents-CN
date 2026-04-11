import { create } from 'zustand'
import { persist } from 'zustand/middleware'
import * as authApi from '@/services/api/auth'
import type { User, LoginForm, RegisterForm } from '@/types/auth.types'
import { isTokenExpired, isValidJwtFormat } from '@/utils/token'

interface AuthState {
  token: string | null
  refreshToken: string | null
  user: User | null
  isAuthenticated: boolean
  isLoading: boolean
  error: string | null
  redirectPath: string
  hasRehydrated: boolean
}

interface AuthActions {
  login: (form: LoginForm) => Promise<boolean>
  register: (form: RegisterForm) => Promise<boolean>
  logout: () => Promise<void>
  fetchUserInfo: () => Promise<boolean>
  refreshAccessToken: () => Promise<boolean>
  clearAuth: () => void
  setRedirectPath: (path: string) => void
  updateUser: (user: Partial<User>) => void
  /** 由 HTTP 拦截器调用，更新 token（不触发持久化写入循环） */
  setToken: (token: string) => void
  setRefreshToken: (token: string) => void
}

type AuthStore = AuthState & AuthActions

export const useAuthStore = create<AuthStore>()(
  persist(
    (set, get) => ({
      token: null,
      refreshToken: null,
      user: null,
      isAuthenticated: false,
      isLoading: false,
      error: null,
      redirectPath: '/dashboard',
      hasRehydrated: false,

      login: async (form) => {
        set({ isLoading: true, error: null })
        try {
          const res = await authApi.login(form)
          if (res.success && res.data) {
            set({
              token: res.data.access_token,
              refreshToken: res.data.refresh_token,
              user: res.data.user,
              isAuthenticated: true,
              isLoading: false,
            })
            return true
          }
          set({ error: res.message || '登录失败', isLoading: false })
          return false
        } catch (err) {
          const message = err instanceof Error ? err.message : '登录失败'
          set({ error: message, isLoading: false })
          return false
        }
      },

      register: async (form) => {
        set({ isLoading: true, error: null })
        try {
          const res = await authApi.register(form)
          set({ isLoading: false })
          return res.success
        } catch (err) {
          const message = err instanceof Error ? err.message : '注册失败'
          set({ error: message, isLoading: false })
          return false
        }
      },

      logout: async () => {
        try {
          await authApi.logout()
        } finally {
          get().clearAuth()
        }
      },

      fetchUserInfo: async () => {
        try {
          const res = await authApi.getUserInfo()
          if (res.success && res.data) {
            set({ user: res.data })
            return true
          }
          return false
        } catch {
          return false
        }
      },

      refreshAccessToken: async () => {
        const currentRefreshToken = get().refreshToken
        if (!currentRefreshToken) {
          get().clearAuth()
          return false
        }

        try {
          const res = await authApi.refreshToken(currentRefreshToken)
          if (res.success && res.data?.access_token) {
            set({
              token: res.data.access_token,
              refreshToken: res.data.refresh_token ?? currentRefreshToken,
              isAuthenticated: true,
            })
            return true
          }
          get().clearAuth()
          return false
        } catch {
          get().clearAuth()
          return false
        }
      },

      clearAuth: () => {
        set({
          token: null,
          refreshToken: null,
          user: null,
          isAuthenticated: false,
          error: null,
        })
      },

      setRedirectPath: (path) => set({ redirectPath: path }),

      setToken: (token: string) => set({ token, isAuthenticated: true }),

      setRefreshToken: (token: string) => set({ refreshToken: token }),

      updateUser: (partial) => {
        const { user } = get()
        if (user) {
          set({ user: { ...user, ...partial } })
        }
      },
    }),
    {
      name: 'auth-store',
      partialize: (state) => ({
        token: state.token,
        refreshToken: state.refreshToken,
        user: state.user,
        redirectPath: state.redirectPath,
      }),
      onRehydrateStorage: () => (state) => {
        if (state) {
          state.hasRehydrated = true
          if (state.token) {
            // 初始化时检查 token 是否有效
            if (!isValidJwtFormat(state.token) || isTokenExpired(state.token)) {
              state.clearAuth()
            } else {
              state.isAuthenticated = true
            }
          }
        }
      },
    }
  )
)

/**
 * 初始化认证刷新定时器（应在 App.tsx useEffect 中调用）
 */
export function startAuthRefreshTimer(): () => void {
  const check = async () => {
    const { token, refreshAccessToken, clearAuth } = useAuthStore.getState()
    if (!token) return

    // 如果 token 即将在 5 分钟内过期，提前刷新
    const { getTokenRemainingTime } = await import('@/utils/token')
    const remaining = getTokenRemainingTime(token)
    if (remaining > 0 && remaining < 300) {
      const success = await refreshAccessToken()
      if (!success) clearAuth()
    } else if (remaining <= 0) {
      clearAuth()
    }
  }

  check()
  const timer = setInterval(check, 60000)
  return () => clearInterval(timer)
}
