/**
 * 格式化金额（人民币）
 */
export function formatCurrency(value: number, currency = '¥'): string {
  if (value == null || isNaN(value)) return '--'
  if (Math.abs(value) >= 1e8) {
    return `${currency}${(value / 1e8).toFixed(2)}亿`
  }
  if (Math.abs(value) >= 1e4) {
    return `${currency}${(value / 1e4).toFixed(2)}万`
  }
  return `${currency}${value.toFixed(2)}`
}

/**
 * 格式化百分比
 */
export function formatPercent(value: number | null | undefined, decimals = 2): string {
  if (value == null || isNaN(value)) return '--'
  const sign = value > 0 ? '+' : ''
  return `${sign}${value.toFixed(decimals)}%`
}

/**
 * 格式化大数字（亿、万）
 */
export function formatLargeNumber(value: number | null | undefined): string {
  if (value == null || isNaN(value)) return '--'
  if (Math.abs(value) >= 1e8) return `${(value / 1e8).toFixed(2)}亿`
  if (Math.abs(value) >= 1e4) return `${(value / 1e4).toFixed(2)}万`
  return value.toFixed(2)
}

/**
 * 格式化成交量
 */
export function formatVolume(value: number | null | undefined): string {
  if (value == null || isNaN(value)) return '--'
  if (value >= 1e8) return `${(value / 1e8).toFixed(2)}亿手`
  if (value >= 1e4) return `${(value / 1e4).toFixed(2)}万手`
  return `${value.toFixed(0)}手`
}

/**
 * 格式化成交额
 */
export function formatAmount(value: number | null | undefined): string {
  if (value == null || isNaN(value)) return '--'
  if (value >= 1e8) return `${(value / 1e8).toFixed(2)}亿`
  if (value >= 1e4) return `${(value / 1e4).toFixed(2)}万`
  return value.toFixed(2)
}

/**
 * 获取涨跌色
 */
export function getChangeColor(value: number | null | undefined): string {
  if (value == null || value === 0) return 'var(--text-primary)'
  return value > 0 ? 'var(--accent-error)' : 'var(--accent-success)'
}

/**
 * 格式化股票价格
 */
export function formatPrice(value: number | null | undefined, decimals = 2): string {
  if (value == null || isNaN(value)) return '--'
  return value.toFixed(decimals)
}
