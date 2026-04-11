import dayjs from 'dayjs'

/**
 * 格式化日期
 */
export function formatDate(date: string | Date, format = 'YYYY-MM-DD'): string {
  return dayjs(date).format(format)
}

/**
 * 格式化日期时间
 */
export function formatDateTime(date: string | Date): string {
  return dayjs(date).format('YYYY-MM-DD HH:mm:ss')
}

/**
 * 格式化相对时间（几分钟前等）
 */
export function formatRelativeTime(date: string | Date): string {
  const now = dayjs()
  const target = dayjs(date)
  const diffSeconds = now.diff(target, 'second')

  if (diffSeconds < 60) return '刚刚'
  if (diffSeconds < 3600) return `${Math.floor(diffSeconds / 60)} 分钟前`
  if (diffSeconds < 86400) return `${Math.floor(diffSeconds / 3600)} 小时前`
  if (diffSeconds < 2592000) return `${Math.floor(diffSeconds / 86400)} 天前`
  return formatDate(date)
}

/**
 * 判断是否为交易日（简化版，仅排除周末）
 */
export function isTradingDay(date?: string | Date): boolean {
  const d = dayjs(date)
  const day = d.day()
  return day !== 0 && day !== 6
}
