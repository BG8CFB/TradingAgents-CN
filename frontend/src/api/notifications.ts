import { ApiClient } from './request'

export interface NotificationItem {
  id: string
  title: string
  content?: string
  type: 'analysis' | 'alert' | 'system'
  status: 'unread' | 'read'
  created_at: string
  link?: string
  source?: string
}

export interface NotificationListResponse {
  items: NotificationItem[]
  total?: number
  page?: number
  page_size?: number
}

export const notificationsApi = {
  async getUnreadCount(): Promise<{ success: boolean; data: { count: number } }> {
    try {
      return await ApiClient.get('/api/notifications/unread_count')
    } catch (e) {
      console.warn('[Notifications] 获取未读计数失败:', e)
      return { success: false, data: { count: 0 } }
    }
  },

  async getList(params?: { status?: 'unread' | 'all'; page?: number; page_size?: number; type?: string }): Promise<{ success: boolean; data: NotificationListResponse }> {
    const query = new URLSearchParams()
    if (params?.status) query.set('status', params.status)
    if (params?.page) query.set('page', String(params.page))
    if (params?.page_size) query.set('page_size', String(params.page_size))
    if (params?.type) query.set('type', params.type)
    const url = query.toString() ? `/api/notifications?${query.toString()}` : '/api/notifications'
    try {
      return await ApiClient.get(url)
    } catch (e) {
      console.warn('[Notifications] 获取通知列表失败:', e)
      return { success: false, data: { items: [], total: 0, page: params?.page ?? 1, page_size: params?.page_size ?? 20 } }
    }
  },

  async markRead(id: string): Promise<{ success: boolean }> {
    try {
      return await ApiClient.post(`/api/notifications/${id}/read`)
    } catch (e) {
      console.warn('[Notifications] 标记已读失败:', e)
      return { success: false }
    }
  },

  async markAllRead(): Promise<{ success: boolean }> {
    try {
      return await ApiClient.post('/api/notifications/read_all')
    } catch (e) {
      console.warn('[Notifications] 全部标记已读失败:', e)
      return { success: false }
    }
  }
}
