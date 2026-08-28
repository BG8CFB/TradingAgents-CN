/**
 * 轮询 composable：定时刷新 + 页面不可见时暂停
 *
 * 用法：
 *   const { lastRefreshTime } = usePolling(loadData, 60_000)
 */

import { ref, onMounted, onUnmounted } from 'vue'

export function usePolling(fn: () => unknown | Promise<unknown>, intervalMs = 60_000) {
  const lastRefreshTime = ref<string>('')
  let timer: ReturnType<typeof setInterval> | null = null

  const run = async () => {
    await fn()
    lastRefreshTime.value = new Date().toLocaleTimeString('zh-CN', { hour12: false })
  }

  const start = () => {
    if (timer !== null) return
    timer = setInterval(run, intervalMs)
  }

  const stop = () => {
    if (timer !== null) {
      clearInterval(timer)
      timer = null
    }
  }

  const onVisibilityChange = () => {
    // 页面不可见时暂停轮询，回到前台恢复并立即刷新一次
    if (document.visibilityState === 'hidden') {
      stop()
    } else {
      start()
      void run()
    }
  }

  onMounted(() => {
    start()
    document.addEventListener('visibilitychange', onVisibilityChange)
  })

  onUnmounted(() => {
    stop()
    document.removeEventListener('visibilitychange', onVisibilityChange)
  })

  return { lastRefreshTime, refreshNow: run, stopPolling: stop, startPolling: start }
}
