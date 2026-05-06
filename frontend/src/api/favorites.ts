import { ApiClient } from './request'

/**
 * 将股票代码规范化为后端期望的格式：
 * - A股: 去除 .SH/.SZ/.BJ 后缀，保留 6 位纯数字（如 "000001.SZ" → "000001"）
 * - 港股: 去除 .HK 后缀，保留 5 位纯数字（如 "00700.HK" → "00700"）
 * - 美股: 大写字母代码（如 "aapl" → "AAPL"）
 */
function normalizeStockCode(code: string): string {
  if (!code) return ''
  const trimmed = code.trim().toUpperCase()
  // A股/港股带后缀：去除 .SH/.SZ/.BJ/.SS/.HK
  const stripped = trimmed.replace(/\.(SH|SZ|BJ|SS|HK)$/i, '')
  // A股纯数字补零到6位
  if (/^\d{1,6}$/.test(stripped)) {
    return stripped.padStart(6, '0')
  }
  // 港股纯数字补零到5位（去.HK后）
  if (/^\d{1,5}$/.test(stripped) && (code.toUpperCase().endsWith('.HK') || stripped.length <= 5)) {
    return stripped.padStart(5, '0')
  }
  return stripped
}

export interface FavoriteItem {
  symbol?: string  // 主字段：6位股票代码
  stock_code?: string  // 兼容字段（已废弃）
  stock_name: string
  market: string
  board?: string
  exchange?: string
  added_at?: string
  tags?: string[]
  notes?: string
  alert_price_high?: number | null
  alert_price_low?: number | null
  current_price?: number | null
  change_percent?: number | null
  volume?: number | null
}

export interface AddFavoriteReq {
  symbol?: string  // 主字段：6位股票代码
  stock_code?: string  // 兼容字段（已废弃）
  stock_name: string
  market?: string
  tags?: string[]
  notes?: string
  alert_price_high?: number | null
  alert_price_low?: number | null
}

export const favoritesApi = {
  /**
   * 获取收藏列表
   */
  list: () => ApiClient.get<FavoriteItem[]>('/api/favorites/'),

  /**
   * 添加收藏
   * 后端要求 stock_code 必填且为纯数字格式（A股6位/港股5位/美股字母）
   */
  add: (payload: AddFavoriteReq) => {
    const rawCode = payload.stock_code || payload.symbol || ''
    const body = {
      ...payload,
      stock_code: normalizeStockCode(rawCode),
      symbol: payload.symbol || rawCode
    }
    return ApiClient.post<{ message: string; symbol?: string; stock_code?: string }>('/api/favorites/', body)
  },

  /**
   * 更新收藏
   * @param symbol 股票代码（6位）
   * @param payload 更新内容
   */
  update: (symbol: string, payload: Partial<Pick<FavoriteItem, 'tags' | 'notes' | 'alert_price_high' | 'alert_price_low'>>) =>
    ApiClient.put<{ message: string; symbol?: string; stock_code?: string }>(`/api/favorites/${symbol}`, payload),

  /**
   * 删除收藏
   * @param symbol 股票代码（6位）
   */
  remove: (symbol: string) => ApiClient.delete<{ message: string; symbol?: string; stock_code?: string }>(`/api/favorites/${symbol}`),

  /**
   * 检查是否已收藏
   * @param symbol 股票代码（6位）
   */
  check: (symbol: string) => ApiClient.get<{ symbol?: string; stock_code?: string; is_favorite: boolean }>(`/api/favorites/check/${symbol}`),

  /**
   * 获取所有标签
   */
  tags: () => ApiClient.get<string[]>('/api/favorites/tags'),

  /**
   * 同步自选股实时行情
   * @param data_source 数据源（tushare/akshare）
   */
  syncRealtime: (data_source: string = 'tushare') =>
    ApiClient.post<{
      total: number
      success_count: number
      failed_count: number
      symbols: string[]
      data_source: string
      message: string
    }>('/api/favorites/sync-realtime', { data_source })
}

