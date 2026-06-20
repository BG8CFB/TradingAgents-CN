import { defineStore } from 'pinia'
import { ElMessage } from 'element-plus'
import type { Router } from 'vue-router'
import { authApi } from '@/api/auth'
import type { User, LoginForm, RegisterForm } from '@/types/auth'

export interface AuthState {
  // 认证状态
  isAuthenticated: boolean
  token: string | null
  refreshToken: string | null

  // 用户信息
  user: User | null

  // 权限信息
  permissions: string[]
  roles: string[]

  // 登录状态
  loginLoading: boolean

  // 重定向路径
  redirectPath: string
}

// 路由实例注入入口（由 main.ts 在创建 router 后调用 setAppRouter 注入）
let appRouter: Router | null = null

export function setAppRouter(router: Router): void {
  appRouter = router
}

/**
 * JWT token 合法性校验（纯函数，无副作用）：
 * - 非字符串或为空 → 无效
 * - mock token（mock-token 或 mock-* 前缀）→ 无效
 * - JWT 三段式结构不完整 → 无效
 * - payload.exp 已过期 → 无效
 *
 * state 工厂与 cleanupInvalidAuthStorage 共用此函数，避免重复定义。
 */
function isValidAuthToken(t: string | null): boolean {
  if (!t || typeof t !== 'string') return false
  if (t === 'mock-token' || t.startsWith('mock-')) return false
  const parts = t.split('.')
  if (parts.length !== 3) return false
  try {
    const payload = JSON.parse(atob(parts[1]))
    if (payload.exp && payload.exp * 1000 < Date.now()) return false
  } catch {
    return false
  }
  return true
}

/**
 * 清理无效的本地认证存储（mock token / 格式非法 / 已过期）。
 *
 * 从 state 工厂抽出，避免 state 初始化阶段产生副作用。
 * 由 main.ts 的 initApp 在使用 store 之前显式调用一次。
 */
export function cleanupInvalidAuthStorage(): void {
  const token = localStorage.getItem('auth-token') || null
  const refreshToken = localStorage.getItem('refresh-token') || null

  // mock token 在 cleanup 阶段输出告警（state 工厂的纯函数版本静默）
  if (token && (token === 'mock-token' || token.startsWith('mock-'))) {
    console.warn('⚠️ 检测到mock token，将被清除:', token)
  }
  if (refreshToken && (refreshToken === 'mock-token' || refreshToken.startsWith('mock-'))) {
    console.warn('⚠️ 检测到mock refresh token，将被清除:', refreshToken)
  }
  // 过期 token 输出统一告警
  if (token && !isValidAuthToken(token) && !token.startsWith('mock-')) {
    console.warn('Token 已过期或格式无效，将被清除')
  }

  // user-info JSON 合法性校验（防止与有效 token 配对的损坏 user-info 导致 user: null 不一致）
  const userInfo = localStorage.getItem('user-info')
  if (userInfo) {
    try { JSON.parse(userInfo) } catch { localStorage.removeItem('user-info') }
  }

  const validToken = isValidAuthToken(token)
  const validRefreshToken = isValidAuthToken(refreshToken)

  if (!validToken || !validRefreshToken) {
    console.log('🧹 清除无效的认证信息')
    localStorage.removeItem('auth-token')
    localStorage.removeItem('refresh-token')
    localStorage.removeItem('user-info')
  }
}

export const useAuthStore = defineStore('auth', {
  state: (): AuthState => {
    // TODO(安全): JWT Token 当前存储在 localStorage 中，存在 XSS 攻击窃取风险。
    // 长期方案：改为 HttpOnly Cookie + SameSite=Strict，需后端配合实现。
    // 参考：https://cheatsheetseries.owasp.org/cheatsheets/JSON_Web_Token_for_Java_Cheat_Sheet.html
    // 注意：state 工厂保持纯净（仅读），无效 token 的清理由 cleanupInvalidAuthStorage() 在应用启动时执行。
    const token = localStorage.getItem('auth-token') || null
    const refreshToken = localStorage.getItem('refresh-token') || null

    const validToken = isValidAuthToken(token) ? token : null
    const validRefreshToken = isValidAuthToken(refreshToken) ? refreshToken : null

    // 持久化 user-info：恢复时同步提取 roles，避免路由守卫"窗口期"误把 admin 拦截到 dashboard
    const user: User | null = validToken
      ? (() => { try { const raw = localStorage.getItem('user-info'); return raw ? JSON.parse(raw) as User : null } catch { return null } })()
      : null

    // roles 优先从 localStorage 显式缓存读取（最稳）；缺失时从 user.is_admin 兜底
    const cachedRoles: string[] = (() => {
      try {
        const raw = localStorage.getItem('auth-roles')
        if (!raw) return []
        const parsed = JSON.parse(raw)
        return Array.isArray(parsed) ? parsed : []
      } catch { return [] }
    })()
    const roles: string[] = cachedRoles.length > 0
      ? cachedRoles
      : (user?.is_admin ? ['admin'] : [])

    return {
      isAuthenticated: !!validToken,
      token: validToken,
      refreshToken: validRefreshToken,

      user,

      permissions: [],
      roles,

      loginLoading: false,
      redirectPath: '/'
    }
  },

  getters: {
    // 用户头像：优先使用用户设置的头像，否则返回 undefined 使用默认图标
    userAvatar(): string | undefined {
      return this.user?.avatar || undefined
    },
    
    // 用户显示名称
    userDisplayName(): string {
      return this.user?.username || this.user?.email || '未知用户'
    },
    
    // 是否为管理员
    isAdmin(): boolean {
      return this.roles.includes('admin')
    },

    // roles 是否已加载完成（用于路由守卫等待异步 fetchUserInfo）
    rolesLoaded(): boolean {
      return this.roles.length > 0
    },
    
    // 检查权限
    hasPermission(): (permission: string) => boolean {
      return (permission: string) => {
        return this.permissions.includes(permission) || this.isAdmin
      }
    },
    
    // 检查角色
    hasRole(): (role: string) => boolean {
      return (role: string) => {
        return this.roles.includes(role)
      }
    },
    
    // 用户统计信息
    userStats(): Record<string, number> {
      return {
        totalAnalyses: this.user?.total_analyses || 0,
        successfulAnalyses: this.user?.successful_analyses || 0,
        failedAnalyses: this.user?.failed_analyses || 0,
        dailyQuota: this.user?.daily_quota || 1000,
        concurrentLimit: this.user?.concurrent_limit || 3
      }
    }
  },

  actions: {
    // 设置认证信息
    setAuthInfo(token: string, refreshToken?: string, user?: User) {
      this.token = token
      this.isAuthenticated = true

      if (refreshToken) {
        this.refreshToken = refreshToken
      }

      if (user) {
        this.user = user
        // 同步从 user.roles 推断 roles，保证 setAuthInfo 调用方未显式给 roles 时也有合理初值
        const userRoles = (user as any)?.roles
        if (Array.isArray(userRoles) && userRoles.length > 0) {
          this.roles = userRoles
        } else if (user.is_admin) {
          this.roles = ['admin']
        }
      }

      // 手动保存到localStorage（确保持久化）
      localStorage.setItem('auth-token', token)
      if (refreshToken) {
        localStorage.setItem('refresh-token', refreshToken)
      }
      if (user) {
        localStorage.setItem('user-info', JSON.stringify(user))
      }
      // roles 持久化：刷新页面后路由守卫立即知道是否 admin，避免 fetchUserInfo 完成前的误伤
      if (this.roles.length > 0) {
        localStorage.setItem('auth-roles', JSON.stringify(this.roles))
      }

      // 设置API请求头
      this.setAuthHeader(token)

      console.log('✅ 认证信息已保存:', {
        token: token ? '已设置' : '未设置',
        refreshToken: refreshToken ? '已设置' : '未设置',
        user: user ? user.username : '未设置',
        roles: this.roles,
        isAuthenticated: this.isAuthenticated
      })
    },

    // 清除认证信息
    clearAuthInfo() {
      this.token = null
      this.refreshToken = null
      this.user = null
      this.isAuthenticated = false
      this.permissions = []
      this.roles = []

      // 清除API请求头
      this.setAuthHeader(null)

      // 清除本地存储（含 roles 缓存）
      localStorage.removeItem('auth-token')
      localStorage.removeItem('refresh-token')
      localStorage.removeItem('user-info')
      localStorage.removeItem('auth-roles')
    },

    /**
     * 等待 roles 加载完成（最多 timeoutMs 毫秒）。
     *
     * 用于路由守卫：应用冷启动时若直接访问 admin 页面，roles 可能尚未从
     * 后端 /me 拉取到。守卫调用此 action 等待，避免误把 admin 重定向到 dashboard。
     * 配合 state 工厂从 localStorage 恢复 roles 的设计，绝大多数情况下立即返回。
     */
    async waitForRoles(timeoutMs = 2000): Promise<boolean> {
      if (this.roles.length > 0) return true
      const start = Date.now()
      while (Date.now() - start < timeoutMs) {
        await new Promise(resolve => setTimeout(resolve, 50))
        if (this.roles.length > 0) return true
      }
      return false
    },

    // 跳转到登录页（SPA 内导航，避免整页刷新）
    redirectToLogin() {
      if (typeof window === 'undefined') return
      const currentPath = window.location.pathname
      if (currentPath === '/login') return
      console.log('🔄 跳转到登录页...')
      if (appRouter) {
        appRouter.push('/login')
      } else {
        // 兜底：尚未注入 router（早期初始化阶段），回退到整页跳转
        console.warn('[auth] appRouter 未注入，redirectToLogin 退化为整页跳转，请检查 main.ts setAppRouter 调用时序')
        window.location.href = '/login'
      }
    },
    
    // 设置API请求头
    setAuthHeader(_token: string | null) {
      // 这里会在API模块中设置Authorization头
      // 具体实现在api/request.ts中
    },
    
    // 登录
    async login(loginForm: LoginForm) {
      // 防止重复登录请求
      if (this.loginLoading) {
        console.log('⏭️ 登录请求进行中，跳过重复调用')
        return false
      }

      try {
        this.loginLoading = true

        const response = await authApi.login(loginForm)

        if (response.success) {
          // csrf_token：login 响应中显式返回，写入 state 供调试与启动校验使用；
          // 实际 CSRF Cookie 已由后端 Set-Cookie 自动写入
          const { access_token, refresh_token, user, csrf_token } = response.data

          // 设置认证信息
          this.setAuthInfo(access_token, refresh_token, user)

          // 后端响应已包含 roles 字段，优先采用；为兼容旧后端，缺失时退回 admin 兜底
          const userRoles = (user as any)?.roles
            || ((user as any)?.is_admin ? ['admin'] : ['user'])
          this.roles = Array.isArray(userRoles) ? userRoles : ['user']
          // 同步持久化 roles，刷新后路由守卫立即可用，避免 fetchUserInfo 窗口期误判
          localStorage.setItem('auth-roles', JSON.stringify(this.roles))
          // 开源版admin拥有所有权限
          this.permissions = ['*']

          // 同步用户偏好设置到 appStore
          this.syncUserPreferencesToAppStore()

          // 启动 token 自动刷新定时器
          const { setupTokenRefreshTimer } = await import('@/utils/auth')
          setupTokenRefreshTimer()

          if (import.meta.env.DEV) {
            console.log('✅ 登录完成：CSRF token 已', csrf_token ? '下发' : '缺失（建议启动时补刷）')
          }

          // 不在这里显示成功消息，由调用方显示
          return true
        } else {
          // 不在这里显示错误消息，由调用方显示
          return false
        }
      } catch (error: any) {
        console.error('登录失败:', error)
        // 不在这里显示错误消息，由调用方显示
        return false
      } finally {
        this.loginLoading = false
      }
    },
    
    // 注册
    async register(registerForm: RegisterForm) {
      try {
        const response = await authApi.register(registerForm)
        
        if (response.success) {
          ElMessage.success('注册成功，请登录')
          return true
        } else {
          ElMessage.error(response.message || '注册失败')
          return false
        }
      } catch (error: any) {
        console.error('注册失败:', error)
        ElMessage.error(error.message || '注册失败，请重试')
        return false
      }
    },
    
    // 登出
    async logout() {
      try {
        // 调用登出API
        await authApi.logout()
        // 清除 token 刷新定时器
        const { clearTokenRefreshTimer } = await import('@/utils/auth')
        clearTokenRefreshTimer()
        // 断开通知 WebSocket，避免登出后旧 token 继续触发重连
        try {
          const { useNotificationStore } = await import('./notifications')
          useNotificationStore().disconnect()
        } catch (e) {
          console.warn('断开通知连接失败:', e)
        }
      } catch (error) {
        console.error('登出API调用失败:', error)
      } finally {
        // 无论API调用是否成功，都清除本地认证信息
        this.clearAuthInfo()
        console.log('✅ 用户已登出，认证信息已清除')

        // 跳转到登录页
        this.redirectToLogin()
      }
    },
    
    // 刷新Token
    async refreshAccessToken() {
      try {
        console.log('🔄 开始刷新Token...')

        if (!this.refreshToken) {
          console.warn('❌ 没有refresh token，无法刷新')
          throw new Error('没有刷新令牌')
        }

        if (import.meta.env.DEV) {
          console.log('📝 Refresh token信息:', {
            length: this.refreshToken.length,
            prefix: this.refreshToken.substring(0, 10),
            isValid: this.refreshToken.split('.').length === 3
          })
        }

        // 验证refresh token格式
        if (this.refreshToken.split('.').length !== 3) {
          console.error('❌ Refresh token格式无效')
          throw new Error('Refresh token格式无效')
        }

        const response = await authApi.refreshToken(this.refreshToken)
        console.log('📨 刷新响应:', response)

        if (response.success) {
          const { access_token, refresh_token } = response.data
          console.log('✅ Token刷新成功')
          this.setAuthInfo(access_token, refresh_token)
          return true
        } else {
          console.error('❌ Token刷新失败:', response.message)
          throw new Error(response.message || 'Token刷新失败')
        }
      } catch (error: any) {
        console.error('❌ Token刷新异常:', error)

        // 如果是网络错误或服务器错误，不要立即清除认证信息
        if (error.code === 'NETWORK_ERROR' || error.response?.status >= 500) {
          console.warn('⚠️ 网络或服务器错误，保留认证信息')
          return false
        }

        // 其他错误（如401），清除认证信息
        console.log('🧹 清除认证信息并跳转登录')
        this.clearAuthInfo()
        this.redirectToLogin()

        return false
      }
    },
    
    // 获取用户信息
    async fetchUserInfo() {
      try {
        console.log('📡 正在获取用户信息...')
        const response = await authApi.getUserInfo()

        if (response.success) {
          this.user = response.data
          this.isAuthenticated = true
          // 后端 /me 已返回 roles；缺失时基于 is_admin 兜底，保证路由守卫不误判
          const userRoles = (response.data as any)?.roles
            || (response.data?.is_admin ? ['admin'] : ['user'])
          this.roles = Array.isArray(userRoles) ? userRoles : ['user']
          // 持久化最新 roles，避免本地缓存与后端权限变更不一致
          localStorage.setItem('auth-roles', JSON.stringify(this.roles))
          console.log('✅ 用户信息获取成功:', this.user?.username)

          // 同步用户偏好设置到 appStore
          this.syncUserPreferencesToAppStore()

          return true
        } else {
          console.warn('⚠️ 获取用户信息失败:', response.message)
          throw new Error(response.message || '获取用户信息失败')
        }
      } catch (error) {
        console.error('❌ 获取用户信息失败:', error)
        // 重新抛出错误，让上层处理
        throw error
      }
    },
    
    // 开源版不需要权限检查，admin拥有所有权限
    // roles 已由 login 响应或 fetchUserInfo 接口写入；此处仅同步 permissions，
    // 不再硬编码覆盖 roles，避免普通用户被错误授予 admin 权限
    async fetchUserPermissions() {
      this.permissions = ['*']
      // 兼容老后端：若 user.is_admin 为 true 但 roles 未下发，则补 admin
      if (this.roles.length === 0) {
        this.roles = this.user?.is_admin ? ['admin'] : ['user']
        localStorage.setItem('auth-roles', JSON.stringify(this.roles))
      }
      return true
    },
    
    // 更新用户信息
    async updateUserInfo(userInfo: Partial<User>) {
      try {
        const response = await authApi.updateUserInfo(userInfo)

        if (response.success) {
          this.user = { ...this.user!, ...response.data }

          // 同步用户偏好设置到 appStore
          this.syncUserPreferencesToAppStore()

          ElMessage.success('用户信息更新成功')
          return true
        } else {
          ElMessage.error(response.message || '更新失败')
          return false
        }
      } catch (error: any) {
        console.error('更新用户信息失败:', error)
        ElMessage.error(error.message || '更新失败，请重试')
        return false
      }
    },
    
    // 同步用户偏好设置到 appStore
    syncUserPreferencesToAppStore() {
      if (!this.user?.preferences) return

      // 动态导入 appStore 避免循环依赖
      import('./app').then(({ useAppStore }) => {
        const appStore = useAppStore()
        const prefs = this.user!.preferences

        // 同步主题设置
        if (prefs.ui_theme) {
          appStore.setTheme(prefs.ui_theme as 'light' | 'dark' | 'auto')
        }

        // 同步侧边栏宽度
        if (prefs.sidebar_width) {
          appStore.setSidebarWidth(prefs.sidebar_width)
        }

        // 同步语言设置
        if (prefs.language) {
          appStore.setLanguage(prefs.language as 'zh-CN' | 'en-US')
        }

        // 同步分析偏好
        if (prefs.default_market || prefs.default_debate_rounds !== undefined || prefs.auto_refresh !== undefined || prefs.refresh_interval) {
          appStore.updatePreferences({
            defaultMarket: prefs.default_market as any,
            defaultDebateRounds: prefs.default_debate_rounds,
            autoRefresh: prefs.auto_refresh,
            refreshInterval: prefs.refresh_interval
          })
        }

        console.log('✅ 用户偏好设置已同步到 appStore')
      })
    },

    // 修改密码
    async changePassword(oldPassword: string, newPassword: string, confirmPassword?: string) {
      try {
        const response = await authApi.changePassword({
          old_password: oldPassword,
          new_password: newPassword,
          confirm_password: confirmPassword || newPassword
        })

        if (response.success) {
          ElMessage.success('密码修改成功')
          return true
        } else {
          ElMessage.error(response.message || '密码修改失败')
          return false
        }
      } catch (error: any) {
        console.error('修改密码失败:', error)
        ElMessage.error(error.message || '修改密码失败，请重试')
        return false
      }
    },
    
    // 设置重定向路径
    setRedirectPath(path: string) {
      this.redirectPath = path
    },
    
    // 获取并清除重定向路径
    getAndClearRedirectPath(): string {
      const path = this.redirectPath || '/dashboard'
      this.redirectPath = '/dashboard'
      return path
    },
    
    // 检查认证状态
    async checkAuthStatus() {
      if (this.token) {
        try {
          console.log('🔍 检查token有效性...')
          // 验证token是否有效
          const valid = await this.fetchUserInfo()
          if (valid) {
            this.isAuthenticated = true
            await this.fetchUserPermissions()
            console.log('✅ 认证状态验证成功')
          } else {
            // Token无效，尝试刷新
            console.log('🔄 Token无效，尝试刷新...')
            await this.refreshAccessToken()
          }
        } catch (error) {
          console.error('❌ 检查认证状态失败:', error)
          // 网络超时不代表 token 失效，本地已通过 isValidToken() 验证过格式和过期时间
          // 此时不应修改 isAuthenticated，避免路由守卫误判导致导航被拦截
          if ((error as any).code === 'ECONNABORTED' || (error as any).message?.includes('timeout')) {
            console.warn('⚠️ 网络超时，保持当前认证状态（本地 token 仍然有效）')
            // 不要修改 isAuthenticated，保持与本地 token 一致
          } else {
            // 其他错误（如 401）则清除认证信息
            this.clearAuthInfo()
            this.redirectToLogin()
          }
        }
      } else {
        console.log('📝 没有token，跳过认证检查')
      }
    }
  }
})
