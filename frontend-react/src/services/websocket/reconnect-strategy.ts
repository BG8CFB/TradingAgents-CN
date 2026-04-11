/**
 * WebSocket 指数退避重连策略
 * @param connect 连接函数
 * @param onStateChange 状态变更回调
 * @returns 清理函数
 */
export function websocketReconnectStrategy(
  connect: () => void,
  onStateChange?: (connecting: boolean) => void,
  maxAttempts = 10
): () => void {
  let attempts = 0
  let timer: ReturnType<typeof setTimeout> | null = null

  const tryReconnect = () => {
    if (attempts >= maxAttempts) {
      onStateChange?.(false)
      return
    }

    attempts++
    const delay = Math.min(1000 * Math.pow(2, attempts - 1), 30000)
    onStateChange?.(true)

    timer = setTimeout(() => {
      connect()
    }, delay)
  }

  tryReconnect()

  return () => {
    if (timer) {
      clearTimeout(timer)
      timer = null
    }
  }
}
