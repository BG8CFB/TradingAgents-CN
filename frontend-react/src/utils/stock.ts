import { detectMarket, type MarketType } from './market'

/** 股票代码验证规则 */
const STOCK_CODE_PATTERNS: Record<MarketType, RegExp> = {
  CN: /^\d{6}$/,
  HK: /^\d{4,5}(\.HK)?$/,
  US: /^[A-Z]{1,6}$/,
}

/**
 * 验证股票代码是否合法
 */
export function validateStockCode(code: string, market?: MarketType): { valid: boolean; message: string } {
  if (!code || !code.trim()) {
    return { valid: false, message: '请输入股票代码' }
  }

  const m = market ?? detectMarket(code)
  const pattern = STOCK_CODE_PATTERNS[m]

  if (!pattern.test(code.trim().toUpperCase())) {
    const examples: Record<MarketType, string> = {
      CN: '6位数字，如 000001',
      HK: '4-5位数字，如 00700',
      US: '1-6位字母，如 AAPL',
    }
    return { valid: false, message: `${m} 股票代码格式不正确，${examples[m]}` }
  }

  return { valid: true, message: '' }
}

/**
 * 格式化股票代码（统一大小写等）
 */
export function normalizeStockCode(code: string): string {
  const trimmed = code.trim().toUpperCase()
  // A股补零
  if (/^\d{1,5}$/.test(trimmed) && detectMarket(trimmed) === 'CN') {
    return trimmed.padStart(6, '0')
  }
  return trimmed
}

/**
 * 获取股票代码的搜索关键词（去除后缀）
 */
export function getStockCodeSearchKey(code: string): string {
  return code.replace(/\.(SZ|SH|HK|US|BJ)$/i, '')
}
