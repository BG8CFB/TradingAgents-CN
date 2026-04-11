import { describe, it, expect } from 'vitest'
import { validateStockCode, normalizeStockCode, getStockCodeSearchKey } from '@/utils/stock'

describe('stock utils', () => {
  describe('validateStockCode', () => {
    it('validates A股 codes', () => {
      expect(validateStockCode('000001').valid).toBe(true)
      expect(validateStockCode('600519').valid).toBe(true)
      expect(validateStockCode('123').valid).toBe(false)
    })

    it('validates 美股 codes', () => {
      expect(validateStockCode('AAPL').valid).toBe(true)
      expect(validateStockCode('TSLA').valid).toBe(true)
      expect(validateStockCode('AAPL123').valid).toBe(false)
    })

    it('validates 港股 codes', () => {
      expect(validateStockCode('00700').valid).toBe(true)
      expect(validateStockCode('0700.HK').valid).toBe(true)
    })
  })

  describe('normalizeStockCode', () => {
    it('pads A股 codes to 6 digits', () => {
      expect(normalizeStockCode('1')).toBe('000001')
      expect(normalizeStockCode('600519')).toBe('600519')
    })

    it('uppercases letters', () => {
      expect(normalizeStockCode('aapl')).toBe('AAPL')
    })
  })

  describe('getStockCodeSearchKey', () => {
    it('removes exchange suffixes', () => {
      expect(getStockCodeSearchKey('000001.SZ')).toBe('000001')
      expect(getStockCodeSearchKey('00700.HK')).toBe('00700')
    })
  })
})
