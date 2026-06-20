/**
 * CSRF Token 工具集（双提交 Cookie 模式）。
 *
 * 设计参考：OWASP CSRF Prevention Cheat Sheet — Double Submit Cookie。
 *
 * 1. **Cookie 来源**：登录/注册/刷新 token 时由后端 Set-Cookie 写入（HttpOnly=false；
 *    前端 JS 需读取，用于注入 X-CSRF-Token header）。
 * 2. **兜底获取**：本地 Cookie 丢失或过期时，通过 GET /api/auth/csrf-token
 *    主动拉取并刷新 Cookie。
 * 3. **请求注入**：见 request.ts 拦截器；仅 POST/PUT/PATCH/DELETE 写入 header。
 */

export const CSRF_COOKIE_NAME = 'csrf_token'

/**
 * 从 document.cookie 读取 csrf_token。
 * Cookie 形如 "key1=v1; key2=v2; csrf_token=xxx"，需正则匹配。
 */
export function getCsrfToken(): string | null {
  if (typeof document === 'undefined' || !document.cookie) return null
  const match = document.cookie.match(
    new RegExp('(?:^|;\\s*)' + CSRF_COOKIE_NAME + '=([^;]+)')
  )
  if (!match || !match[1]) return null
  try {
    return decodeURIComponent(match[1])
  } catch {
    return match[1]
  }
}

/**
 * 启动时或检测到 CSRF Cookie 缺失时调用：通过 GET /api/auth/csrf-token
 * 主动向后端请求新 token，后端会一并下发 Set-Cookie。
 *
 * 调用前提：用户已登录（携带 Authorization 头）。未登录场景返回 false 即可，
 * 因为登录成功后会立即由 setAuthInfo 写入新 Cookie。
 *
 * 返回值：true 表示成功刷新；false 表示网络失败或未登录。
 */
export async function ensureCsrfToken(): Promise<boolean> {
  // 已存在 Cookie 则无需再请求
  if (getCsrfToken()) return true

  try {
    // 动态导入 request 避免与 useAuthStore 形成循环依赖
    const { default: request } = await import('./request')
    await request.get('/api/auth/csrf-token')
    return !!getCsrfToken()
  } catch (err) {
    console.warn('[csrf] 获取 CSRF token 失败:', err)
    return false
  }
}
