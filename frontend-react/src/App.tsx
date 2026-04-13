import { useEffect, useMemo } from 'react'
import { ConfigProvider, theme, App as AntApp } from 'antd'
import zhCN from 'antd/locale/zh_CN'
import { RouterProvider } from 'react-router-dom'
import { router } from './router'
import { startAuthRefreshTimer } from '@/stores/auth.store'
import { useAppStore, getEffectiveTheme } from '@/stores/app.store'
import ErrorBoundary from '@/components/ui/ErrorBoundary'
import NetworkStatus from '@/components/feedback/NetworkStatus'
import { setGlobalMessage } from '@/services/http/message-ref'

function App() {
  const appTheme = useAppStore((state) => state.theme)
  const { message } = AntApp.useApp()

  useEffect(() => {
    const stopTimer = startAuthRefreshTimer()
    return () => stopTimer()
  }, [])

  useEffect(() => {
    // antd AppContext 默认 message 为 {}，需校验 methods 存在才注册
    if (message && typeof message.error === 'function') {
      setGlobalMessage(message)
    }
  }, [message])

  const effectiveTheme = getEffectiveTheme(appTheme)

  useEffect(() => {
    document.documentElement.setAttribute('data-theme', effectiveTheme)
  }, [effectiveTheme])

  const antTheme = useMemo(
    () => ({
      algorithm: effectiveTheme === 'dark' ? theme.darkAlgorithm : theme.defaultAlgorithm,
      token: {
        /* 主色 - 雅金 */
        colorPrimary: '#C9A96E',
        colorInfo: '#4A7DB8',
        /* 股票红绿 - 保持不变 */
        colorSuccess: '#52C41A',
        colorError: '#FF4D4F',
        colorWarning: '#D48806',
        /* 背景系统 - 暖白 */
        colorBgBase: effectiveTheme === 'dark' ? '#131314' : '#FAF8F5',
        colorBgContainer: effectiveTheme === 'dark' ? '#1A1A1D' : '#FFFFFF',
        colorBgElevated: effectiveTheme === 'dark' ? '#222225' : '#FFFFFF',
        colorBgLayout: effectiveTheme === 'dark' ? '#131314' : '#FAF8F5',
        /* 文字系统 */
        colorText: effectiveTheme === 'dark' ? '#EDEDED' : '#2C2C2C',
        colorTextSecondary: effectiveTheme === 'dark' ? '#9CA3AF' : '#6B7280',
        /* 边框 */
        colorBorder: effectiveTheme === 'dark' ? 'rgba(201, 169, 110, 0.18)' : 'rgba(201, 169, 110, 0.22)',
        colorBorderSecondary: effectiveTheme === 'dark' ? 'rgba(201, 169, 110, 0.12)' : 'rgba(201, 169, 110, 0.14)',
        /* 圆角与字体 */
        borderRadius: 6,
        fontFamily: `'Inter', -apple-system, 'PingFang SC', 'Microsoft YaHei', sans-serif`,
        /* 链接色 - 钢蓝 */
        colorLink: '#4A7DB8',
        colorLinkHover: '#5B8FC4',
      },
      components: {
        Layout: {
          headerBg: effectiveTheme === 'dark' ? '#131314' : '#FDFBFA',
          headerHeight: 56,
          headerPadding: '0 24px',
          siderBg: effectiveTheme === 'dark' ? '#131314' : '#FDFBFA',
        },
        Menu: {
          itemBg: 'transparent',
          itemSelectedBg: effectiveTheme === 'dark' ? 'rgba(201, 169, 110, 0.18)' : 'rgba(201, 169, 110, 0.12)',
          itemSelectedColor: '#C9A96E',
          itemHoverBg: effectiveTheme === 'dark' ? 'rgba(201, 169, 110, 0.08)' : 'rgba(201, 169, 110, 0.06)',
          itemColor: '#6B7280',
        },
        Button: {
          primaryShadow: 'none',
        },
        Card: {
          colorBgContainer: effectiveTheme === 'dark' ? '#1A1A1D' : '#FFFFFF',
          colorBorderSecondary: effectiveTheme === 'dark' ? 'rgba(201, 169, 110, 0.18)' : 'rgba(201, 169, 110, 0.22)',
        },
        Table: {
          colorBgContainer: effectiveTheme === 'dark' ? '#1A1A1D' : '#FFFFFF',
          headerBg: effectiveTheme === 'dark' ? '#1A1A1D' : '#FDFBFA',
          rowHoverBg: effectiveTheme === 'dark' ? 'rgba(201, 169, 110, 0.10)' : 'rgba(201, 169, 110, 0.06)',
        },
        Input: {
          colorBgContainer: effectiveTheme === 'dark' ? '#1A1A1D' : '#FAF8F5',
          activeBorderColor: '#C9A96E',
          hoverBorderColor: 'rgba(201, 169, 110, 0.45)',
        },
        Select: {
          colorBgContainer: effectiveTheme === 'dark' ? '#1A1A1D' : '#FAF8F5',
        },
        Modal: {
          contentBg: effectiveTheme === 'dark' ? '#1A1A1D' : '#FFFFFF',
        },
      },
    }),
    [effectiveTheme]
  )

  return (
    <ConfigProvider locale={zhCN} theme={antTheme}>
      <AntApp>
        <ErrorBoundary>
          <NetworkStatus />
          <RouterProvider router={router} />
        </ErrorBoundary>
      </AntApp>
    </ConfigProvider>
  )
}

export default App
