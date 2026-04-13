/** 全局错误消息去重 */
const recentMessages = new Map<string, number>()
const MESSAGE_DEDUP_INTERVAL = 3000 // 3秒内相同消息不重复弹

/**
 * 显示错误消息（带去重）
 * @param message 错误消息
 * @returns 是否实际显示了消息
 */
export function showError(message: string): boolean {
  const now = Date.now()
  const lastShown = recentMessages.get(message)

  if (lastShown && now - lastShown < MESSAGE_DEDUP_INTERVAL) {
    return false
  }

  recentMessages.set(message, now)

  // 使用 Ant Design message 组件（延迟导入避免循环依赖）
  import('./message-ref').then(({ globalMessage: gMessage }) => {
    // antd AppContext 默认 message 为 {}，必须校验 error 是否为函数
    if (gMessage && typeof gMessage.error === 'function') {
      gMessage.error(message)
    } else {
      import('antd').then(({ message: antMessage }) => {
        antMessage.error(message)
      }).catch(() => {})
    }
  }).catch(() => {})

  return true
}

/**
 * 根据HTTP状态码获取友好的错误消息
 */
export function getHttpErrorMessage(status: number): string {
  const messages: Record<number, string> = {
    400: '请求参数错误',
    401: '认证已过期，请重新登录',
    403: '权限不足，无法访问',
    404: '请求的资源不存在',
    429: '请求过于频繁，请稍后再试',
    500: '服务器内部错误',
    502: '网关错误',
    503: '服务暂不可用',
    504: '网关超时',
  }
  return messages[status] ?? `请求失败 (${status})`
}

/**
 * 判断是否为可重试的网络错误
 */
export function isRetryableError(error: unknown): boolean {
  if (!error || typeof error !== 'object') return false

  const err = error as { code?: string; response?: { status?: number }; message?: string }

  // 网络断开或超时
  if (err.code === 'ECONNABORTED' || err.code === 'ERR_NETWORK') return true
  if (err.message?.includes('Network Error')) return true
  if (err.message?.includes('timeout')) return true

  // 服务端错误
  const status = err.response?.status
  if (status && [502, 503, 504].includes(status)) return true

  return false
}

/** 清理过期的去重记录 */
setInterval(() => {
  const now = Date.now()
  for (const [msg, time] of recentMessages) {
    if (now - time > MESSAGE_DEDUP_INTERVAL * 2) {
      recentMessages.delete(msg)
    }
  }
}, 10000)
