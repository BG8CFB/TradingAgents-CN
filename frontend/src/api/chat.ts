/**
 * AI 问答选股助手 API（/api/chat）。
 * 消息执行为 202 异步模式：sendMessage 只拿 run_id，回答经 WS /api/chat/ws/{session_id} 推送。
 */
import { ApiClient } from './request'

export interface ChatSession {
  session_id: string
  user_id: string
  /** 首条消息定题；新会话为空串 */
  title: string
  message_count: number
  last_message_preview: string
  status: 'active' | 'archived'
  created_at: string
  updated_at: string
}

/** chat_messages 集合文档（只存 user/assistant 文本） */
export interface ChatMessageDoc {
  session_id: string
  user_id: string
  role: 'user' | 'assistant'
  content: string
  created_at: string
  /** assistant 消息附带的一轮执行元数据（轮次/工具调用数/token/模型） */
  run_meta?: {
    turns?: number
    tool_calls_executed?: number
    total_tokens?: number
    stop_reason?: string
    model?: string
    run_id?: string
  }
}

export interface SessionListResp {
  sessions: ChatSession[]
  total: number
  page: number
  page_size: number
}

export interface SessionDetailResp {
  session: ChatSession
  messages: ChatMessageDoc[]
}

/** POST messages 的 202 响应体 */
export interface SendMessageResp {
  run_id: string
  quota_remaining: number
}

export interface QuotaResp {
  quota_remaining: number
}

export const chatApi = {
  createSession: () =>
    ApiClient.post<{ session_id: string; title: string }>('/api/chat/sessions'),
  listSessions: (page = 1, pageSize = 20) =>
    ApiClient.get<SessionListResp>('/api/chat/sessions', { page, page_size: pageSize }),
  getSession: (sessionId: string) =>
    ApiClient.get<SessionDetailResp>(`/api/chat/sessions/${encodeURIComponent(sessionId)}`),
  deleteSession: (sessionId: string) =>
    ApiClient.delete<{ session_id: string; status: string }>(
      `/api/chat/sessions/${encodeURIComponent(sessionId)}`
    ),
  sendMessage: (sessionId: string, content: string) =>
    ApiClient.post<SendMessageResp>(
      `/api/chat/sessions/${encodeURIComponent(sessionId)}/messages`,
      { content }
    ),
  stopRun: (runId: string) =>
    ApiClient.post<{ run_id: string; stopped: boolean }>(
      `/api/chat/runs/${encodeURIComponent(runId)}/stop`
    ),
  getQuota: () => ApiClient.get<QuotaResp>('/api/chat/quota')
}
