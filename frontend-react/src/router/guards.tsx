import { useAuthStore } from '@/stores/auth.store'
import { isTokenExpired, isValidJwtFormat } from '@/utils/token'

/**
 * 路由进入前认证检查
 * @returns 是否通过认证
 */
export function checkAuth(): boolean {
  const token = useAuthStore.getState().token
  if (!token || !isValidJwtFormat(token)) {
    return false
  }
  return !isTokenExpired(token)
}

/**
 * 路由标题生成
 */
export function getRouteTitle(routeName?: string): string {
  const base = 'TradingAgents'
  if (!routeName) return base
  return `${routeName} | ${base}`
}
