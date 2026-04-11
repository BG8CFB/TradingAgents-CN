export interface NotificationMessage {
  id: string
  title: string
  content?: string
  type: 'analysis' | 'alert' | 'system'
  link?: string
  source?: string
  created_at: string
  status: 'unread' | 'read'
}
