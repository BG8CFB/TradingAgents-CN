import { useEffect, useState, useRef } from 'react'
import { Alert, Space, Button } from 'antd'
import { DisconnectOutlined as AntDisconnectOutlined, ReloadOutlined } from '@ant-design/icons'
import { useAppStore } from '@/stores/app.store'

export default function NetworkStatus() {
  const { networkStatus, setNetworkStatus } = useAppStore()
  const [dismissed, setDismissed] = useState(false)
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  useEffect(() => {
    // 初始化网络状态，离线时直接显示横幅
    setNetworkStatus(navigator.onLine ? 'online' : 'offline')
    const timer = timerRef.current

    const handleOnline = () => {
      setNetworkStatus('online')
      // 网络恢复后重置关闭状态（下次断线时重新提示）
      setDismissed(false)
      if (timerRef.current) clearTimeout(timerRef.current)
    }

    const handleOffline = () => {
      setNetworkStatus('offline')
      // 断网时确保横幅可见
      setDismissed(false)
    }

    window.addEventListener('online', handleOnline)
    window.addEventListener('offline', handleOffline)

    return () => {
      window.removeEventListener('online', handleOnline)
      window.removeEventListener('offline', handleOffline)
      if (timer) clearTimeout(timer)
    }
  }, [setNetworkStatus])

  /** 仅在离线且未手动关闭时渲染横幅 */
  if (networkStatus !== 'offline' || dismissed) return null

  return (
    <div
      style={{
        position: 'fixed',
        top: 0,
        left: 0,
        right: 0,
        zIndex: 9999,
        padding: '8px 24px',
        background: '#FFF7E6',
        borderBottom: '1px solid #FFD591',
      }}
    >
      <Alert
        type="warning"
        banner
        icon={<AntDisconnectOutlined />}
        title={
          <Space>
            <span>网络已断开</span>
            <span style={{ color: '#8C8C8C', fontSize: 12 }}>
              部分功能可能不可用，请检查网络连接
            </span>
          </Space>
        }
        action={
          <Space>
            <Button size="small" icon={<ReloadOutlined />} onClick={() => window.location.reload()}>
              刷新页面
            </Button>
            <Button size="small" type="link" onClick={() => setDismissed(true)}>
              关闭
            </Button>
          </Space>
        }
        closable
        onClose={() => setDismissed(true)}
        style={{ marginBottom: 0 }}
      />
    </div>
  )
}
