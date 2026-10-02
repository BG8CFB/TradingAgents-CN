import { createApp } from 'vue'
import { createPinia } from 'pinia'
import * as ElementPlusIconsVue from '@element-plus/icons-vue'
// Element Plus 模板组件由 unplugin-vue-components 按需自动导入（含组件样式）；
// 此处只集中补命令式服务的样式——业务代码显式 import 的 ElMessage/ElMessageBox
// 与 v-loading 指令不经过 resolver，样式不会自动注入，缺了会裸奔（无样式的消息框/遮罩）
import 'element-plus/es/components/message/style/css'
import 'element-plus/es/components/message-box/style/css'
import 'element-plus/es/components/loading/style/css'
import 'element-plus/theme-chalk/dark/css-vars.css'

import dayjs from 'dayjs'
import 'dayjs/locale/zh-cn'
// dayjs 全局中文 locale：ElDatePicker 等日期组件跟随 dayjs 显示中文
dayjs.locale('zh-cn')

import App from './App.vue'
import router from './router'
import { setupGlobalComponents } from './components'
import { useAuthStore, setAppRouter, cleanupInvalidAuthStorage } from './stores/auth'
import { useAppStore } from './stores/app'
import { setupTokenRefreshTimer } from './utils/auth'
import './styles/index.scss'
import './styles/dark-theme.scss'
import './styles/mobile.scss'

// Vite 编译期注入的应用版本号（来源：frontend/package.json，与 pyproject.toml 保持一致）
declare const __APP_VERSION__: string

// 创建应用实例
const app = createApp(App)

// 注册Element Plus图标
for (const [key, component] of Object.entries(ElementPlusIconsVue)) {
  app.component(key, component)
}

// 使用插件
const pinia = createPinia()
app.use(pinia)
app.use(router)
// Element Plus 组件 locale/size/zIndex/message 全局配置收敛在 App.vue 的
// <el-config-provider>（按需引入模式下 app.use(ElementPlus) 已移除）

// 注册全局组件
setupGlobalComponents(app)

// 全局错误处理
app.config.errorHandler = (err, _vm, info) => {
  console.error('全局错误:', err, info)

  // 检查是否是认证错误
  if (err && typeof err === 'object') {
    const error = err as any
    // 检查错误消息或状态码
    if (
      error.message?.includes('认证失败') ||
      error.message?.includes('登录已过期') ||
      error.message?.includes('Token') ||
      error.response?.status === 401 ||
      error.code === 401
    ) {
      console.log('🔒 全局错误处理：检测到认证错误，跳转登录页')
      const authStore = useAuthStore()
      authStore.clearAuthInfo()
      router.push('/login')
    }
  }

  // 这里可以集成错误监控服务
}

// 全局警告处理
app.config.warnHandler = (msg, _vm, trace) => {
  console.warn('全局警告:', msg, trace)
}

// 初始化认证状态
const initApp = async () => {
  // mount 前只做本地同步初始化（零网络 I/O）：
  // 原实现 mount 前 await「后端连通探测(3s) → 认证检查(5s)」串行链，
  // 后端慢/不可达时白屏最长 8 秒。网络检查全部移到 mount 后并行执行。
  cleanupInvalidAuthStorage()
  setAppRouter(router)

  const authStore = useAuthStore()
  const appStore = useAppStore()

  appStore.applyTheme()
  console.log('🎨 主题已应用:', appStore.theme)

  // 设置网络状态监听
  // main.ts 是 SPA 单例入口，应用生命周期内不卸载，监听器随进程退出回收，无需 removeEventListener
  const handleOnline = () => {
    console.log('🌐 网络已连接')
    appStore.setOnlineStatus(true)
    appStore.checkApiConnection()
  }

  const handleOffline = () => {
    console.log('📱 网络已断开')
    appStore.setOnlineStatus(false)
    appStore.setApiConnected(false)
  }

  window.addEventListener('online', handleOnline)
  window.addEventListener('offline', handleOffline)

  app.mount('#app')
  console.log('🚀 应用已挂载')

  // mount 后并行执行网络初始化（fire-and-forget，不阻塞首屏渲染）。
  // 路由守卫只读 isAuthenticated（state 工厂已从本地存储同步恢复），
  // checkAuthStatus 网络超时不会改动状态，因此并行/失败均不影响已挂载页面
  const authCheck = authStore.checkAuthStatus()
  const authTimeout = new Promise((_, reject) => {
    setTimeout(() => reject(new Error('认证检查超时')), 5000)
  })
  const apiCheck = appStore.checkApiConnection().catch(() => false)

  await Promise.allSettled([
    apiCheck,
    Promise.race([authCheck, authTimeout]).catch((e) => {
      console.warn('⚠️ 认证状态检查失败:', e)
    }),
  ])
  console.log('✅ 启动期网络初始化完成')

  // 已登录但浏览器 CSRF Cookie 丢失（如刚刷新页面或第三方 Cookie 被禁用）时，
  // 主动通过 GET /api/auth/csrf-token 补刷；未登录则跳过，登录后会自动下发
  if (authStore.isAuthenticated) {
    setupTokenRefreshTimer()
    try {
      const { ensureCsrfToken } = await import('./api/csrf')
      await ensureCsrfToken()
    } catch (e) {
      console.warn('⚠️ 启动时补刷 CSRF token 失败（不影响已登录状态）:', e)
    }
  }
}

// 启动应用
initApp().catch((error) => {
  console.error('⚠️ 应用初始化异常:', error)
  // 最后兜底：确保页面至少挂载出来，用户能看到具体错误而非白屏
  if (!document.querySelector('#app')?.hasChildNodes()) {
    app.mount('#app')
  }
})

// 开发环境下的调试信息
if (import.meta.env.DEV) {
  console.log(`🚀 TradingAgents-CN v${__APP_VERSION__} 前端应用已启动`)
  console.log('📊 当前环境:', import.meta.env.MODE)
  console.log('🔗 API地址:', import.meta.env.VITE_API_BASE_URL || '/api')
}
