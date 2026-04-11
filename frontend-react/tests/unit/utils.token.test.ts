import { describe, it, expect } from 'vitest'
import { parseJwtPayload, isValidJwtFormat, isTokenExpired, getTokenRemainingTime } from '@/utils/token'

describe('token utils', () => {
  // 创建一个测试用的 JWT token（签名部分可任意）
  const createTestToken = (payload: Record<string, unknown>): string => {
    const header = btoa(JSON.stringify({ alg: 'HS256', typ: 'JWT' }))
    const body = btoa(JSON.stringify(payload))
    return `${header}.${body}.signature`
  }

  describe('parseJwtPayload', () => {
    it('parses valid token payload', () => {
      const token = createTestToken({ sub: 'user123', exp: 1234567890 })
      const payload = parseJwtPayload(token)
      expect(payload).toEqual({ sub: 'user123', exp: 1234567890 })
    })

    it('returns null for invalid token', () => {
      expect(parseJwtPayload('invalid')).toBeNull()
      expect(parseJwtPayload('header.body')).toBeNull()
    })
  })

  describe('isValidJwtFormat', () => {
    it('validates 3-part JWT format', () => {
      expect(isValidJwtFormat(createTestToken({}))).toBe(true)
      expect(isValidJwtFormat('abc.def')).toBe(false)
      expect(isValidJwtFormat(null)).toBe(false)
    })
  })

  describe('isTokenExpired', () => {
    it('returns true for expired token', () => {
      const token = createTestToken({ exp: Math.floor(Date.now() / 1000) - 10 })
      expect(isTokenExpired(token)).toBe(true)
    })

    it('returns true for token nearing expiration', () => {
      const token = createTestToken({ exp: Math.floor(Date.now() / 1000) + 60 })
      expect(isTokenExpired(token, 300)).toBe(true)
    })

    it('returns false for valid token', () => {
      const token = createTestToken({ exp: Math.floor(Date.now() / 1000) + 3600 })
      expect(isTokenExpired(token)).toBe(false)
    })
  })

  describe('getTokenRemainingTime', () => {
    it('returns remaining seconds', () => {
      const exp = Math.floor(Date.now() / 1000) + 3600
      const token = createTestToken({ exp })
      const remaining = getTokenRemainingTime(token)
      expect(remaining).toBeGreaterThan(3500)
      expect(remaining).toBeLessThanOrEqual(3600)
    })
  })
})
