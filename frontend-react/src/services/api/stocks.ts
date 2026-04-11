import { apiClient } from '../http/client'
import type { ApiResponse } from '@/types/common.types'
import type {
  StockQuote,
  StockFundamentals,
  KlineData,
  StockNews,
  StockBasicInfo,
  MarketQuotes,
  StockListItem,
  CombinedStockData,
  SearchStockResult,
  MarketSummary,
  QuotesSyncStatus,
} from '@/types/stocks.types'

// ========== /api/stocks/* ==========

/** 获取股票实时行情 */
export function getStockQuote(code: string, forceRefresh = false): Promise<ApiResponse<StockQuote>> {
  return apiClient.get<StockQuote>(`/api/stocks/${encodeURIComponent(code)}/quote`, {
    force_refresh: forceRefresh,
  })
}

/** 获取基本面数据 */
export function getStockFundamentals(code: string, source?: string, forceRefresh = false): Promise<ApiResponse<StockFundamentals>> {
  const params: Record<string, unknown> = { force_refresh: forceRefresh }
  if (source) params.source = source
  return apiClient.get<StockFundamentals>(`/api/stocks/${encodeURIComponent(code)}/fundamentals`, params)
}

/** 获取K线数据 */
export function getStockKline(code: string, period = 'day', limit = 120, adj = 'none', forceRefresh = false): Promise<ApiResponse<KlineData>> {
  return apiClient.get<KlineData>(`/api/stocks/${encodeURIComponent(code)}/kline`, {
    period,
    limit,
    adj,
    force_refresh: forceRefresh,
  })
}

/** 获取新闻 */
export function getStockNews(code: string, days = 30, limit = 50): Promise<ApiResponse<StockNews>> {
  return apiClient.get<StockNews>(`/api/stocks/${encodeURIComponent(code)}/news`, { days, limit })
}

// ========== /api/stock-data/* ==========

/** 获取股票基础信息 */
export function getStockBasicInfo(symbol: string): Promise<ApiResponse<StockBasicInfo>> {
  return apiClient.get<StockBasicInfo>(`/api/stock-data/basic-info/${encodeURIComponent(symbol)}`)
}

/** 获取实时行情（stock-data版） */
export function getMarketQuotes(symbol: string): Promise<ApiResponse<MarketQuotes>> {
  return apiClient.get<MarketQuotes>(`/api/stock-data/quotes/${encodeURIComponent(symbol)}`)
}

/** 获取股票列表 */
export function getStockList(market?: string, industry?: string, page = 1, pageSize = 20): Promise<ApiResponse<{ items: StockListItem[]; total: number; page: number; page_size: number }>> {
  const params: Record<string, unknown> = { page, page_size: pageSize }
  if (market) params.market = market
  if (industry) params.industry = industry
  return apiClient.get<{ items: StockListItem[]; total: number; page: number; page_size: number }>(
    '/api/stock-data/list',
    params
  )
}

/** 获取综合数据 */
export function getCombinedStockData(symbol: string): Promise<ApiResponse<CombinedStockData>> {
  return apiClient.get<CombinedStockData>(`/api/stock-data/combined/${encodeURIComponent(symbol)}`)
}

/** 搜索股票 */
export function searchStocks(keyword: string, limit = 10): Promise<ApiResponse<{ data: SearchStockResult[]; total: number; keyword: string; source: string }>> {
  return apiClient.get<{
    data: SearchStockResult[]
    total: number
    keyword: string
    source: string
  }>('/api/stock-data/search', { keyword, limit })
}

/** 获取市场概览 */
export function getMarketSummary(): Promise<ApiResponse<MarketSummary>> {
  return apiClient.get<MarketSummary>('/api/stock-data/markets')
}

/** 获取行情同步状态 */
export function getQuotesSyncStatus(): Promise<ApiResponse<QuotesSyncStatus>> {
  return apiClient.get<QuotesSyncStatus>('/api/stock-data/sync-status/quotes')
}
