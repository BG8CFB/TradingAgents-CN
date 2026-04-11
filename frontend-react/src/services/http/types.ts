import type { ApiResponse, RequestConfig } from '@/types/common.types'

/** HTTP 方法类型 */
export type HttpMethod = 'get' | 'post' | 'put' | 'delete' | 'patch'

/** Axios 请求配置扩展 */
export interface InternalRequestConfig {
  skipAuth?: boolean
  skipErrorHandler?: boolean
  showLoading?: boolean
  retryCount?: number
  retryDelay?: number
  _retry?: boolean
}

/** API 客户端方法 */
export interface ApiClient {
  get<T>(url: string, params?: Record<string, unknown>, config?: RequestConfig): Promise<ApiResponse<T>>
  post<T>(url: string, data?: unknown, config?: RequestConfig): Promise<ApiResponse<T>>
  put<T>(url: string, data?: unknown, config?: RequestConfig): Promise<ApiResponse<T>>
  delete<T>(url: string, config?: RequestConfig): Promise<ApiResponse<T>>
  patch<T>(url: string, data?: unknown, config?: RequestConfig): Promise<ApiResponse<T>>
  upload<T>(url: string, file: File, onProgress?: (progress: number) => void, config?: RequestConfig): Promise<ApiResponse<T>>
  download(url: string, filename?: string, config?: RequestConfig): Promise<void>
}
