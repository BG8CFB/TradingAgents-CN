import { create } from 'zustand'
import { websocketReconnectStrategy } from '@/services/websocket/reconnect-strategy'
import type { NotificationMessage } from '@/types/notification.types'

interface NotificationState {
  notifications: NotificationMessage[]
  unreadCount: number
  wsConnected: boolean
  wsConnecting: boolean
}

interface NotificationActions {
  addNotification: (notification: NotificationMessage) => void
  markAsRead: (id: string) => void
  markAllAsRead: () => void
  removeNotification: (id: string) => void
  clearAll: () => void
  setWsConnected: (connected: boolean) => void
  setWsConnecting: (connecting: boolean) => void
}

type NotificationStore = NotificationState & NotificationActions

export const useNotificationStore = create<NotificationStore>((set) => ({
  notifications: [],
  unreadCount: 0,
  wsConnected: false,
  wsConnecting: false,

  addNotification: (notification) => {
    set((state) => {
      // 去重：同ID替换
      const filtered = state.notifications.filter((n) => n.id !== notification.id)
      const newNotifications = [notification, ...filtered].slice(0, 100)
      const unreadCount = newNotifications.filter((n) => n.status === 'unread').length
      return { notifications: newNotifications, unreadCount }
    })
  },

  markAsRead: (id) => {
    set((state) => {
      const notifications = state.notifications.map((n) =>
        n.id === id ? { ...n, status: 'read' as const } : n
      )
      return {
        notifications,
        unreadCount: notifications.filter((n) => n.status === 'unread').length,
      }
    })
  },

  markAllAsRead: () => {
    set((state) => ({
      notifications: state.notifications.map((n) => ({ ...n, status: 'read' as const })),
      unreadCount: 0,
    }))
  },

  removeNotification: (id) => {
    set((state) => {
      const notifications = state.notifications.filter((n) => n.id !== id)
      return {
        notifications,
        unreadCount: notifications.filter((n) => n.status === 'unread').length,
      }
    })
  },

  clearAll: () => set({ notifications: [], unreadCount: 0 }),

  setWsConnected: (wsConnected) => set({ wsConnected }),
  setWsConnecting: (wsConnecting) => set({ wsConnecting }),
}))

/**
 * 启动 WebSocket 通知连接
 */
export function startNotificationWebSocket(token: string): () => void {
  const store = useNotificationStore.getState()
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  const wsUrl = `${protocol}//${window.location.host}/api/ws/notifications?token=${token}`

  let ws: WebSocket | null = null
  let cleanupReconnect = () => {}

  const connect = () => {
    store.setWsConnecting(true)
    ws = new WebSocket(wsUrl)

    ws.onopen = () => {
      store.setWsConnected(true)
      store.setWsConnecting(false)
    }

    ws.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data)
        if (msg.type === 'notification' && msg.data) {
          store.addNotification(msg.data)
        } else if (msg.type === 'connected') {
          console.log('[WS] Notifications connected')
        }
      } catch {
        console.warn('[WS] Invalid message format')
      }
    }

    ws.onclose = () => {
      store.setWsConnected(false)
      store.setWsConnecting(false)
      cleanupReconnect = websocketReconnectStrategy(connect, (connecting) =>
        store.setWsConnecting(connecting)
      )
    }

    ws.onerror = () => {
      store.setWsConnected(false)
      ws?.close()
    }
  }

  connect()

  return () => {
    cleanupReconnect()
    ws?.close()
    store.setWsConnected(false)
  }
}
