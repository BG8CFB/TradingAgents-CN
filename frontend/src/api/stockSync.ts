/**
 * 股票数据同步 API（兼容层）
 *
 * 原 stock-sync 后端端点已废弃，现在转发到新版数据层 API。
 * 新代码请直接使用 @/api/cnData 中的 refreshStock / triggerSync。
 */

import { ApiClient } from './request'
import type { ApiResponse } from './request'

export interface SingleStockSyncRequest {
  symbol: string
  sync_realtime?: boolean
  sync_historical: boolean
  sync_financial: boolean
  sync_basic?: boolean
  data_source: 'tushare' | 'akshare'
  days: number
}

export interface BatchStockSyncRequest {
  symbols: string[]
  sync_historical: boolean
  sync_financial: boolean
  sync_basic?: boolean
  data_source: 'tushare' | 'akshare'
  days: number
}

export interface SyncResult {
  success: boolean
  records?: number
  message?: string
  error?: string
}

export interface SingleStockSyncResponse {
  symbol: string
  realtime_sync: SyncResult | null
  historical_sync: SyncResult | null
  financial_sync: SyncResult | null
  basic_sync: SyncResult | null
}

export interface BatchStockSyncResponse {
  total: number
  symbols: string[]
  historical_sync: {
    success_count: number
    error_count: number
    total_records: number
    message: string
  } | null
  financial_sync: {
    success_count: number
    error_count: number
    total_symbols: number
    message: string
  } | null
  basic_sync: {
    success_count: number
    error_count: number
    total_symbols: number
    message: string
  } | null
}

export interface StockSyncStatus {
  symbol: string
  historical_data: {
    last_sync: string | null
    last_date: string | null
    total_records: number
  }
  financial_data: {
    last_sync: string | null
    last_report_period: string | null
    total_records: number
  }
}

/**
 * 将旧版单股同步请求转换为新版 refreshStock API
 */
function buildRefreshDomains(req: SingleStockSyncRequest): string[] {
  const domains: string[] = []
  if (req.sync_basic) domains.push('basic_info')
  if (req.sync_historical) {
    domains.push('daily_quotes')
    domains.push('daily_indicators')
  }
  if (req.sync_financial) domains.push('financial_data')
  return domains
}

export const stockSyncApi = {
  /**
   * 同步单个股票数据 — 转发到新版 /api/cn/data/refresh/{symbol}
   */
  async syncSingle(request: SingleStockSyncRequest): Promise<ApiResponse<SingleStockSyncResponse>> {
    const domains = buildRefreshDomains(request)
    try {
      const res = await ApiClient.post(`/api/cn/data/refresh/${request.symbol}`, {
        domains,
        force: true,
      }, { timeout: 120000 })

      if (!res.success || !res.data) {
        return {
          success: false,
          data: {
            symbol: request.symbol,
            realtime_sync: null,
            historical_sync: null,
            financial_sync: null,
            basic_sync: null,
          },
          message: res.message || '同步失败',
        }
      }

      const rd = res.data as any
      const result: SingleStockSyncResponse = {
        symbol: request.symbol,
        realtime_sync: null,
        historical_sync: null,
        financial_sync: null,
        basic_sync: null,
      }

      const _isSuccess = (s: string | undefined) => s === 'refreshed' || s === 'fresh'

      if (rd.domains) {
        if (rd.domains.daily_quotes) {
          result.historical_sync = {
            success: _isSuccess(rd.domains.daily_quotes.status),
            records: rd.domains.daily_quotes.records || 0,
            error: rd.domains.daily_quotes.error || undefined,
          }
        }
        if (rd.domains.financial_data) {
          result.financial_sync = {
            success: _isSuccess(rd.domains.financial_data.status),
            records: rd.domains.financial_data.records || 0,
            error: rd.domains.financial_data.error || undefined,
          }
        }
        if (rd.domains.basic_info) {
          result.basic_sync = {
            success: _isSuccess(rd.domains.basic_info.status),
            records: rd.domains.basic_info.records || 0,
            error: rd.domains.basic_info.error || undefined,
          }
        }
      }

      return { success: true, data: result, message: 'ok' }
    } catch (err: any) {
      return {
        success: false,
        data: {
          symbol: request.symbol,
          realtime_sync: null,
          historical_sync: null,
          financial_sync: null,
          basic_sync: null,
        },
        message: err.message || '同步失败',
      }
    }
  },

  /**
   * 批量同步股票数据 — 逐个调用新版 refreshStock
   */
  async syncBatch(request: BatchStockSyncRequest): Promise<ApiResponse<BatchStockSyncResponse>> {
    const domains: string[] = []
    if (request.sync_basic) domains.push('basic_info')
    if (request.sync_historical) {
      domains.push('daily_quotes')
      domains.push('daily_indicators')
    }
    if (request.sync_financial) domains.push('financial_data')

    let successCount = 0
    let errorCount = 0
    let totalRecords = 0

    for (const symbol of request.symbols) {
      try {
        const res = await ApiClient.post(`/api/cn/data/refresh/${symbol}`, {
          domains,
          force: true,
        }, { timeout: 300000 })

        if (res.success) {
          successCount++
          const rd = res.data as any
          if (rd?.domains) {
            for (const d of Object.values(rd.domains) as any[]) {
              totalRecords += d?.records || 0
            }
          }
        } else {
          errorCount++
        }
      } catch {
        errorCount++
      }
    }

    return {
      success: errorCount === 0,
      data: {
        total: request.symbols.length,
        symbols: request.symbols,
        historical_sync: {
          success_count: successCount,
          error_count: errorCount,
          total_records: totalRecords,
          message: `完成 ${successCount}/${request.symbols.length}`,
        },
        financial_sync: null,
        basic_sync: null,
      },
      message: 'ok',
    }
  },

  /**
   * 获取股票同步状态（兼容接口）
   */
  async getStatus(symbol: string): Promise<ApiResponse<StockSyncStatus>> {
    try {
      await ApiClient.get(`/api/cn/data/refresh/${symbol}/status`)
      return {
        success: true,
        data: {
          symbol,
          historical_data: { last_sync: null, last_date: null, total_records: 0 },
          financial_data: { last_sync: null, last_report_period: null, total_records: 0 },
        },
        message: 'ok',
      }
    } catch {
      return {
        success: false,
        data: {
          symbol,
          historical_data: { last_sync: null, last_date: null, total_records: 0 },
          financial_data: { last_sync: null, last_report_period: null, total_records: 0 },
        },
        message: '获取状态失败',
      }
    }
  }
}
