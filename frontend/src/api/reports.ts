/**
 * 报告管理 API
 *
 * 注意：download 方法使用底层 request 实例而非 ApiClient，因为需要
 * responseType: 'blob' 而 ApiClient 的类型签名不直接支持此参数。
 * 其他方法（CRUD）统一使用 ApiClient 保持风格一致。
 */
import { ApiClient, request, type ApiResponse } from './request'

export interface ReportItem {
  id: string
  title?: string
  stock_code?: string
  stock_name?: string
  symbol?: string
  market?: string
  analysis_date?: string
  created_at?: string
  status?: string
  [key: string]: any
}

export interface ReportListResponse {
  reports: ReportItem[]
  total: number
}

export interface ReportDetail extends ReportItem {
  summary?: string
  recommendation?: string
  modules?: Record<string, any>
  [key: string]: any
}

export const reportsApi = {
  /**
   * 获取报告列表
   */
  list(params?: {
    page?: number
    page_size?: number
    search_keyword?: string
    market_filter?: string
    start_date?: string
    end_date?: string
    stock_code?: string
  }): Promise<ApiResponse<ReportListResponse>> {
    return ApiClient.get('/api/reports/list', params)
  },

  /**
   * 获取报告详情
   */
  detail(reportId: string): Promise<ApiResponse<ReportDetail>> {
    return ApiClient.get(`/api/reports/${reportId}/detail`)
  },

  /**
   * 获取报告模块内容
   */
  moduleContent(reportId: string, module: string): Promise<ApiResponse<any>> {
    return ApiClient.get(`/api/reports/${reportId}/content/${module}`)
  },

  /**
   * 删除报告
   */
  delete(reportId: string): Promise<ApiResponse<any>> {
    return ApiClient.delete(`/api/reports/${reportId}`)
  },

  /**
   * 下载报告（返回 Blob 供调用方处理文件名）
   * 使用底层 request 而非 ApiClient，因为需要 responseType: 'blob'
   * 且不需要 ApiResponse 包装（响应拦截器对 blob 直接透传）
   */
  download(reportId: string, format: string = 'markdown'): Promise<any> {
    return request.get(`/api/reports/${reportId}/download`, {
      params: { format },
      responseType: 'blob'
    })
  }
}
