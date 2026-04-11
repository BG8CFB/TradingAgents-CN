/** 自选股 */
export interface FavoriteStock {
  stock_code: string
  stock_name: string
  market: string
  added_at: string
  tags: string[]
  notes: string
  alert_price_high?: number | null
  alert_price_low?: number | null
  current_price?: number | null
  change_percent?: number | null
  volume?: number | null
}

/** 添加自选股请求 */
export interface AddFavoriteRequest {
  stock_code: string
  stock_name: string
  market?: string
  tags?: string[]
  notes?: string
  alert_price_high?: number | null
  alert_price_low?: number | null
}

/** 更新自选股请求 */
export interface UpdateFavoriteRequest {
  tags?: string[] | null
  notes?: string | null
  alert_price_high?: number | null
  alert_price_low?: number | null
}

/** 检查自选股响应 */
export interface CheckFavoriteResponse {
  stock_code: string
  is_favorite: boolean
}

/** 用户标签 */
export interface FavoriteTag {
  name: string
  count: number
}

/** 同步实时行情请求 */
export interface SyncFavoritesRequest {
  data_source?: string
}

/** 同步实时行情响应 */
export interface SyncFavoritesResponse {
  total: number
  success_count: number
  failed_count: number
  symbols: string[]
  data_source: string
  message?: string
}
