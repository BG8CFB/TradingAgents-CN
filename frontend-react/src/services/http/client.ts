import axios from 'axios'
import type { AxiosInstance, AxiosError, InternalAxiosRequestConfig } from 'axios'
import type { ApiResponse, RequestConfig } from '@/types/common.types'
import type { InternalRequestConfig } from './types'
import { showError, getHttpErrorMessage, isRetryableError } from './error-handler'
import { useAuthStore } from '@/stores/auth.store'

const BASE_URL = import.meta.env.VITE_API_BASE_URL || ''
const DEFAULT_TIMEOUT = 60000

/** Axios 实例 */
const instance: AxiosInstance = axios.create({
  baseURL: BASE_URL,
  timeout: DEFAULT_TIMEOUT,
  headers: {
    'Content-Type': 'application/json',
    'Cache-Control': 'no-cache',
    Pragma: 'no-cache',
  },
})

// ========== 401 防抖 ==========
let isHandling401 = false
let handle401Promise: Promise<void> | null = null

type AuthSnapshot = {
  token: string | null
  refreshToken: string | null
}

const authSnapshot: AuthSnapshot = {
  token: useAuthStore.getState().token,
  refreshToken: useAuthStore.getState().refreshToken,
}

// 通过订阅维护模块内快照，避免每次请求都与 store 读取时机强耦合。
useAuthStore.subscribe((state) => {
  authSnapshot.token = state.token
  authSnapshot.refreshToken = state.refreshToken
})

/** 获取存储的 Token（从 Zustand persist 读取） */
function getStoredToken(): string | null {
  return authSnapshot.token
}

/** 获取存储的刷新 Token（从 Zustand persist 读取） */
function getStoredRefreshToken(): string | null {
  return authSnapshot.refreshToken
}

/** 清除认证信息并跳转登录 */
function clearAuthAndRedirect(): void {
  useAuthStore.getState().clearAuth()

  if (window.location.pathname !== '/login') {
    window.location.href = '/login'
  }
}

/** 刷新 Token */
async function refreshAccessToken(): Promise<string | null> {
  const refreshToken = getStoredRefreshToken()
  if (!refreshToken) return null

  try {
    const response = await axios.post(`${BASE_URL}/api/auth/refresh`, {
      refresh_token: refreshToken,
    })
    const { success, data } = response.data
    if (success && data?.access_token) {
      // 同步更新 Zustand store（而非仅写 localStorage）
      const authStore = useAuthStore.getState()
      authStore.setToken(data.access_token)
      if (data.refresh_token) {
        authStore.setRefreshToken?.(data.refresh_token)
      }
      return data.access_token
    }
    return null
  } catch {
    return null
  }
}

/** 统一处理 401 */
async function handle401(): Promise<void> {
  if (isHandling401) {
    return handle401Promise ?? Promise.resolve()
  }

  isHandling401 = true
  handle401Promise = (async () => {
    try {
      const newToken = await refreshAccessToken()
      if (!newToken) {
        clearAuthAndRedirect()
      }
    } finally {
      isHandling401 = false
      handle401Promise = null
    }
  })()

  return handle401Promise
}

// ========== 请求拦截器 ==========
instance.interceptors.request.use(
  (config: InternalAxiosRequestConfig) => {
    const internalConfig = config as InternalAxiosRequestConfig & InternalRequestConfig

    // 注入认证 Token
    if (!internalConfig.skipAuth) {
      const token = getStoredToken()
      if (token) {
        config.headers.Authorization = `Bearer ${token}`
      }
    }

    // 请求追踪 ID
    const requestId = `req_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`
    config.headers['X-Request-ID'] = requestId

    // 语言设置
    config.headers['Accept-Language'] = 'zh-CN'

    return config
  },
  (error) => Promise.reject(error)
)

// ========== 响应拦截器 ==========
instance.interceptors.response.use(
  async (response) => {
    const data = response.data as ApiResponse

    // 检查业务层错误码（40101/40102/40103 等同 401）
    if (data.code && [40101, 40102, 40103].includes(data.code)) {
      const config = response.config as InternalAxiosRequestConfig & InternalRequestConfig
      if (!config._retry) {
        config._retry = true
        await handle401()

        const newToken = getStoredToken()
        if (newToken) {
          config.headers.Authorization = `Bearer ${newToken}`
          return instance(config)
        }
      }

      return Promise.reject(new Error(data.message || '认证已过期'))
    }

    return response
  },
  async (error: AxiosError<ApiResponse>) => {
    const config = error.config as (InternalAxiosRequestConfig & InternalRequestConfig) | undefined
    if (!config) return Promise.reject(error)

    const status = error.response?.status

    // 401 处理：尝试刷新 Token 后重试
    if (status === 401 && !config._retry) {
      config._retry = true
      await handle401()

      const newToken = getStoredToken()
      if (newToken) {
        config.headers.Authorization = `Bearer ${newToken}`
        return instance(config)
      }
    }

    // 网络错误重试
    const maxRetries = config.retryCount ?? 2
    const currentRetry = ((config as unknown) as Record<string, unknown>).__retryCount as number ?? 0
    if (isRetryableError(error) && currentRetry < maxRetries) {
      ((config as unknown) as Record<string, unknown>).__retryCount = currentRetry + 1
      const delay = config.retryDelay ?? Math.pow(2, currentRetry) * 1000
      await new Promise((resolve) => setTimeout(resolve, delay))
      return instance(config)
    }

    // 错误提示
    if (!config.skipErrorHandler) {
      if (error.response) {
        const businessMessage = error.response.data?.message
        showError(businessMessage ?? getHttpErrorMessage(status ?? 500))
      } else if (error.code === 'ECONNABORTED') {
        showError('请求超时，请检查网络连接')
      } else if (error.message?.includes('Network Error')) {
        showError('网络连接失败，请检查网络')
      }
    }

    return Promise.reject(error)
  }
)

// ========== API Client ==========
export const apiClient = {
  async get<T>(url: string, params?: Record<string, unknown>, config?: RequestConfig): Promise<ApiResponse<T>> {
    const response = await instance.get(url, { params, ...config })
    return response.data
  },

  async post<T>(url: string, data?: unknown, config?: RequestConfig): Promise<ApiResponse<T>> {
    const response = await instance.post(url, data, config)
    return response.data
  },

  async put<T>(url: string, data?: unknown, config?: RequestConfig): Promise<ApiResponse<T>> {
    const response = await instance.put(url, data, config)
    return response.data
  },

  async delete<T>(url: string, config?: RequestConfig): Promise<ApiResponse<T>> {
    const response = await instance.delete(url, config)
    return response.data
  },

  async patch<T>(url: string, data?: unknown, config?: RequestConfig): Promise<ApiResponse<T>> {
    const response = await instance.patch(url, data, config)
    return response.data
  },

  async upload<T>(
    url: string,
    file: File,
    onProgress?: (progress: number) => void,
    config?: RequestConfig
  ): Promise<ApiResponse<T>> {
    const formData = new FormData()
    formData.append('file', file)
    const response = await instance.post(url, formData, {
      ...config,
      headers: { 'Content-Type': 'multipart/form-data' },
      onUploadProgress: (event) => {
        if (onProgress && event.total) {
          onProgress(Math.round((event.loaded * 100) / event.total))
        }
      },
    })
    return response.data
  },

  async download(url: string, filename?: string, config?: RequestConfig): Promise<void> {
    const response = await instance.get(url, {
      ...config,
      responseType: 'blob',
    })
    const blob = new Blob([response.data])
    const downloadUrl = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = downloadUrl
    link.download = filename ?? 'download'
    document.body.appendChild(link)
    link.click()
    document.body.removeChild(link)
    URL.revokeObjectURL(downloadUrl)
  },
}

export { instance as httpClient }
export default apiClient
