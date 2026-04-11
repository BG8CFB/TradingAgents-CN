import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import dayjs from 'dayjs'
import 'dayjs/locale/zh-cn'
import App from './App'
import './assets/styles/global.css'
import './assets/styles/ant-overrides.css'

dayjs.locale('zh-cn')

// ========== 全局错误捕获 ==========

/** 捕获未处理的 Promise rejection */
window.addEventListener('unhandledrejection', (event) => {
  console.error('[Global] 未处理的 Promise 拒绝:', event.reason)

  // 阻止默认的控制台输出（已自行处理）
  // event.preventDefault() // 取消注释可阻止浏览器默认输出

  const reason = event.reason
  let message = '发生未知错误'

  if (reason instanceof Error) {
    message = reason.message
  } else if (typeof reason === 'string') {
    message = reason
  } else if (reason?.message) {
    message = reason.message
  }

  // 对于网络/超时等已知错误，不弹窗打扰用户
  const knownErrors = ['timeout', 'Network Error', 'ECONNABORTED', 'ERR_NETWORK', 'cancelled']
  const isKnown = knownErrors.some((k) =>
    message.toLowerCase().includes(k.toLowerCase())
  )

  if (!isKnown && import.meta.env.DEV) {
    console.warn('[Global] 建议处理此 Promise 错误:', message)
  }
})

/** 捕获全局 JS 运行时错误 */
window.addEventListener('error', (event) => {
  // 忽略资源加载错误（由 img/script 等标签触发）
  if (event.target !== window) {
    console.warn(
      '[Global] 资源加载失败:',
      (event.target as HTMLElement).tagName,
      (event.target as HTMLImageElement | HTMLScriptElement)?.src ||
      (event.target as HTMLLinkElement)?.href
    )
    return
  }

  console.error('[Global] 全局 JS 错误:', event.message, event.filename, event.lineno, event.colno)
})

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
