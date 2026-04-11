import { apiClient } from '../http/client'
import type { ApiResponse } from '@/types/common.types'
import type {
  FavoriteStock,
  AddFavoriteRequest,
  UpdateFavoriteRequest,
  CheckFavoriteResponse,
  SyncFavoritesRequest,
  SyncFavoritesResponse,
} from '@/types/favorites.types'

/** 获取用户自选股列表 */
export function getFavorites(): Promise<ApiResponse<FavoriteStock[]>> {
  return apiClient.get<FavoriteStock[]>('/api/favorites/')
}

/** 添加自选股 */
export function addFavorite(data: AddFavoriteRequest): Promise<ApiResponse<{ stock_code: string }>> {
  return apiClient.post<{ stock_code: string }>('/api/favorites/', data)
}

/** 更新自选股 */
export function updateFavorite(stockCode: string, data: UpdateFavoriteRequest): Promise<ApiResponse<{ stock_code: string }>> {
  return apiClient.put<{ stock_code: string }>(`/api/favorites/${encodeURIComponent(stockCode)}`, data)
}

/** 删除自选股 */
export function removeFavorite(stockCode: string): Promise<ApiResponse<{ stock_code: string }>> {
  return apiClient.delete<{ stock_code: string }>(`/api/favorites/${encodeURIComponent(stockCode)}`)
}

/** 检查股票是否在自选股中 */
export function checkFavorite(stockCode: string): Promise<ApiResponse<CheckFavoriteResponse>> {
  return apiClient.get<CheckFavoriteResponse>(`/api/favorites/check/${encodeURIComponent(stockCode)}`)
}

/** 获取用户标签 */
export function getFavoriteTags(): Promise<ApiResponse<string[]>> {
  return apiClient.get<string[]>('/api/favorites/tags')
}

/** 同步自选股实时行情 */
export function syncFavoritesRealtime(data?: SyncFavoritesRequest): Promise<ApiResponse<SyncFavoritesResponse>> {
  return apiClient.post<SyncFavoritesResponse>('/api/favorites/sync-realtime', data)
}
