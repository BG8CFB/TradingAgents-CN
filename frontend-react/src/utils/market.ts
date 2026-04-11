/** 市场类型 */
export type MarketType = 'CN' | 'HK' | 'US'

/** 市场信息 */
export interface MarketInfo {
  code: MarketType
  name: string
  shortName: string
  currency: string
  colorUp: string
  colorDown: string
}

/** 所有支持的市场 */
export const MARKETS: Record<MarketType, MarketInfo> = {
  CN: {
    code: 'CN',
    name: 'A股',
    shortName: 'A股',
    currency: 'CNY',
    colorUp: 'var(--accent-error)', // A股红涨
    colorDown: 'var(--accent-success)', // A股绿跌
  },
  HK: {
    code: 'HK',
    name: '港股',
    shortName: '港股',
    currency: 'HKD',
    colorUp: 'var(--accent-success)',
    colorDown: 'var(--accent-error)',
  },
  US: {
    code: 'US',
    name: '美股',
    shortName: '美股',
    currency: 'USD',
    colorUp: 'var(--accent-success)',
    colorDown: 'var(--accent-error)',
  },
}

/**
 * 根据股票代码自动识别市场类型
 */
export function detectMarket(code: string): MarketType {
  const trimmed = code.trim().toUpperCase()

  // 港股：4-5位纯数字 或带 .HK 后缀
  if (/^\d{4,5}$/.test(trimmed) || trimmed.endsWith('.HK')) {
    return 'HK'
  }

  // 美股：纯字母
  if (/^[A-Z]+$/.test(trimmed)) {
    return 'US'
  }

  // 默认A股：6位数字
  return 'CN'
}

/**
 * 获取市场显示名称
 */
export function getMarketName(code: string): string {
  return MARKETS[detectMarket(code)].name
}

/**
 * 获取市场涨跌色
 */
export function getMarketColors(code: string): { up: string; down: string } {
  const market = MARKETS[detectMarket(code)]
  return { up: market.colorUp, down: market.colorDown }
}
