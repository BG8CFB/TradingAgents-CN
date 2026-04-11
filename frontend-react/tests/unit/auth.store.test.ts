import { describe, it, expect, beforeEach, vi } from 'vitest'
import { useAuthStore } from '@/stores/auth.store'
import * as authApi from '@/services/api/auth'

// Mock auth API
vi.mock('@/services/api/auth', () => ({
  login: vi.fn(),
  logout: vi.fn(),
  getUserInfo: vi.fn(),
  refreshToken: vi.fn(),
}))

describe('auth store', () => {
  beforeEach(() => {
    // Reset store state
    useAuthStore.setState({
      token: null,
      refreshToken: null,
      user: null,
      isAuthenticated: false,
      isLoading: false,
      error: null,
      redirectPath: '/dashboard',
    })
    localStorage.clear()
    vi.clearAllMocks()
  })

  describe('login', () => {
    it('sets authenticated state on successful login', async () => {
      const mockLogin = vi.mocked(authApi.login)
      mockLogin.mockResolvedValueOnce({
        success: true,
        message: 'ok',
        data: {
          access_token: 'token123',
          refresh_token: 'refresh123',
          token_type: 'bearer',
          expires_in: 3600,
          user: { id: '1', username: 'test', email: 't@t.com', is_active: true, is_verified: true, is_admin: false, created_at: '', updated_at: '' },
        },
      })

      const result = await useAuthStore.getState().login({ username: 'test', password: 'pass' })

      expect(result).toBe(true)
      expect(useAuthStore.getState().isAuthenticated).toBe(true)
      expect(useAuthStore.getState().token).toBe('token123')
      expect(useAuthStore.getState().user?.username).toBe('test')
    })

    it('sets error on failed login', async () => {
      const mockLogin = vi.mocked(authApi.login)
      mockLogin.mockRejectedValueOnce(new Error('Invalid credentials'))

      const result = await useAuthStore.getState().login({ username: 'test', password: 'wrong' })

      expect(result).toBe(false)
      expect(useAuthStore.getState().isAuthenticated).toBe(false)
      expect(useAuthStore.getState().error).toBe('Invalid credentials')
    })
  })

  describe('logout', () => {
    it('clears auth state', async () => {
      useAuthStore.setState({ token: 'token', isAuthenticated: true })
      vi.mocked(authApi.logout).mockResolvedValueOnce({ success: true, message: 'ok' })

      await useAuthStore.getState().logout()

      expect(useAuthStore.getState().token).toBeNull()
      expect(useAuthStore.getState().isAuthenticated).toBe(false)
    })
  })

  describe('clearAuth', () => {
    it('clears all auth data', () => {
      useAuthStore.setState({
        token: 'token',
        user: { id: '1', username: 'test', email: 't@t.com', is_active: true, is_verified: true, is_admin: false, created_at: '', updated_at: '' },
        isAuthenticated: true,
      })

      useAuthStore.getState().clearAuth()

      expect(useAuthStore.getState().token).toBeNull()
      expect(useAuthStore.getState().user).toBeNull()
      expect(useAuthStore.getState().isAuthenticated).toBe(false)
    })
  })

  describe('updateUser', () => {
    it('merges partial user data', () => {
      useAuthStore.setState({
        user: { id: '1', username: 'test', email: 't@t.com', is_active: true, is_verified: true, is_admin: false, created_at: '', updated_at: '' },
      })

      useAuthStore.getState().updateUser({ username: 'updated' })

      expect(useAuthStore.getState().user?.username).toBe('updated')
      expect(useAuthStore.getState().user?.email).toBe('t@t.com')
    })
  })
})
