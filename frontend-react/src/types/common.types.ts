/** 通用 API 响应结构 */
export interface ApiResponse<T = unknown> {
  success: boolean
  data: T
  message: string
  code?: number
  timestamp?: string
  request_id?: string
}

/** 分页参数 */
export interface PaginationParams {
  page?: number
  page_size?: number
  [key: string]: unknown
}

/** 分页响应 */
export interface PaginatedResponse<T> {
  items: T[]
  total: number
  page: number
  page_size: number
  total_pages: number
}

/** 排序参数 */
export interface SortParams {
  sort_by?: string
  sort_order?: 'asc' | 'desc'
}

/** 请求配置 */
export interface RequestConfig {
  /** 跳过认证（用于登录/注册） */
  skipAuth?: boolean
  /** 跳过全局错误处理 */
  skipErrorHandler?: boolean
  /** 显示全局 loading */
  showLoading?: boolean
  /** 自定义超时（毫秒） */
  timeout?: number
  /** 重试次数 */
  retryCount?: number
  /** 重试延迟（毫秒） */
  retryDelay?: number
}

/** 通用键值对 */
export interface KeyValue {
  key: string
  value: unknown
  label?: string
}

/** 操作结果 */
export interface OperationResult {
  success: boolean
  message?: string
}
