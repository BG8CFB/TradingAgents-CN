import { useAuthStore } from '@/stores/auth.store'

export function useAuth() {
  const { isAuthenticated, user, isLoading, login, logout, clearAuth } = useAuthStore()

  return {
    isAuthenticated,
    user,
    isLoading,
    login,
    logout,
    clearAuth,
  }
}
