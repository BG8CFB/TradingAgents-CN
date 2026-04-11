import { apiClient } from '../http/client'
import type { ApiResponse } from '@/types/common.types'
import type { MarketInfo, MultiMarketStockInfo, MultiMarketQuote, KlineItem } from '@/types/stocks.types'

/** 获取支持的市场列表 */
export function getSupportedMarkets(): Promise<ApiResponse<{ markets: MarketInfo[] }>> {
  return apiClient.get<{ markets: MarketInfo[] }>('/api/markets')
}

/** 搜索股票（多市场） */
export function searchMultiMarketStocks(market: string, q: string, limit = 20): Promise<ApiResponse<{ stocks: MultiMarketStockInfo[]; total: number }>> {
  return apiClient.get<{ stocks: MultiMarketStockInfo[]; total: number }>(
    `/api/markets/${market.toUpperCase()}/stocks/search`,
    { q, limit }
  )
}

/** 获取股票信息（多市场） */
export function getMultiMarketStockInfo(market: string, code: string): Promise<ApiResponse<MultiMarketStockInfo>> {
  return apiClient.get<MultiMarketStockInfo>(`/api/markets/${market.toUpperCase()}/stocks/${encodeURIComponent(code)}/info`)
}

/** 获取实时行情（多市场） */
export function getMultiMarketQuote(market: string, code: string): Promise<ApiResponse<MultiMarketQuote>> {
  return apiClient.get<MultiMarketQuote>(`/api/markets/${market.toUpperCase()}/stocks/${encodeURIComponent(code)}/quote`)
}

/** 获取历史K线（多市场） */
export function getMultiMarketDailyQuotes(
  market: string,
  code: string,
  options?: { start_date?: string; end_date?: string; limit?: number }
): Promise<ApiResponse<{ code: string; market: string; quotes: KlineItem[]; total: number }>> {
  return apiClient.get<{ code: string; market: string; quotes: KlineItem[]; total: number }>(
    `/api/markets/${market.toUpperCase()}/stocks/${encodeURIComponent(code)}/daily`,
    options
  )
}
