/**
 * JWT Token 工具函数
 */

interface JwtPayload {
  exp?: number
  iat?: number
  sub?: string
  [key: string]: unknown
}

/** 已知的 mock token 前缀（测试用） */
const MOCK_TOKEN_PREFIXS = ['mock_', 'test_', 'fake_']

/**
 * 解析 JWT payload
 */
export function parseJwtPayload(token: string): JwtPayload | null {
  try {
    const parts = token.split('.')
    if (parts.length !== 3) return null

    const payload = parts[1]
    const decoded = atob(payload.replace(/-/g, '+').replace(/_/g, '/'))
    return JSON.parse(decoded) as JwtPayload
  } catch {
    return null
  }
}

/**
 * 检查 Token 格式是否为有效 JWT
 */
export function isValidJwtFormat(token: string | null): boolean {
  if (!token) return false
  return token.split('.').length === 3
}

/**
 * 检查是否为 mock token
 */
export function isMockToken(token: string): boolean {
  return MOCK_TOKEN_PREFIXS.some((prefix) => token.startsWith(prefix))
}

/**
 * 检查 Token 是否已过期
 * @param token JWT Token
 * @param bufferSeconds 提前多少秒视为过期（默认 300 秒 = 5 分钟）
 */
export function isTokenExpired(token: string, bufferSeconds = 300): boolean {
  const payload = parseJwtPayload(token)
  if (!payload?.exp) {
    console.warn('isTokenExpired: no payload or exp', payload)
    return true
  }
  const expired = Date.now() / 1000 > payload.exp - bufferSeconds
  console.log('isTokenExpired check', { exp: payload.exp, now: Date.now() / 1000, expired })
  return expired
}

/**
 * 获取 Token 剩余有效时间（秒）
 */
export function getTokenRemainingTime(token: string): number {
  const payload = parseJwtPayload(token)
  if (!payload?.exp) return 0

  return Math.max(0, payload.exp - Date.now() / 1000)
}
