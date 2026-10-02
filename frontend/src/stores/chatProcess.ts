/**
 * AI 问答选股助手 store — 会话列表 + 当前会话消息流 + WS 实时事件。
 *
 * 消息流：POST messages 返回 202（run_id），回答/工具/思考经 WS chat_event 推送；
 * 轮次边界由 turn_done / turn_failed / turn_cancelled 标记。
 * 渲染复用 Analysis/ChatTimeline 的消息类型（user/thinking/assistant/tool），
 * 另加 error 类型承载轮次失败提示。
 */
import { defineStore } from 'pinia'
import { ref } from 'vue'
import { chatApi, type ChatSession, type ChatMessageDoc } from '@/api/chat'
import { useAuthStore } from '@/stores/auth'
import type {
  UserChatMessage,
  ThinkingChatMessage,
  AssistantChatMessage,
  ToolChatMessage
} from '@/components/Analysis/ChatTimeline/buildChatMessages'

export type UIMessage =
  | UserChatMessage
  | ThinkingChatMessage
  | AssistantChatMessage
  | ToolChatMessage
  | { kind: 'error'; id: string; text: string }

/** WS 下行消息（宽松解析） */
interface ChatWSMessage {
  type: string
  event_type?: string
  run_id?: string
  session_id?: string
  seq?: number
  payload?: Record<string, unknown>
  assistant_text?: string
  error?: string
  [key: string]: unknown
}

/** 截断超长文本用于折叠展示（与 ChatTimeline 同规格） */
function truncateText(value: unknown, max = 800): string {
  let text: string
  if (typeof value === 'string') {
    text = value
  } else {
    try {
      text = JSON.stringify(value, null, 2)
    } catch {
      text = String(value)
    }
  }
  if (!text) return ''
  return text.length > max ? `${text.slice(0, max)}…(已截断)` : text
}

let localSeq = -1

export const useChatProcessStore = defineStore('chatProcess', () => {
  // ── state ──
  const sessions = ref<ChatSession[]>([])
  const currentSessionId = ref('')
  const messages = ref<UIMessage[]>([])
  const wsConnected = ref(false)
  /** 当前轮回答执行中（输入框禁用，显示停止按钮） */
  const running = ref(false)
  /** text_delta 实时累积的正文 */
  const streamingText = ref('')
  /** thinking_delta 实时累积的思考（聚合 thinking 事件到达后转为消息气泡） */
  const streamingThinking = ref('')
  const quotaRemaining = ref<number | null>(null)
  /** 功能未启用（POST 503）时置 false，页面显示引导 */
  const chatEnabled = ref(true)
  const lastError = ref('')

  // ── 内部状态 ──
  let ws: WebSocket | null = null
  let reconnectTimer: ReturnType<typeof setTimeout> | null = null
  let reconnectAttempts = 0
  const maxReconnectAttempts = 10
  let intentionalClose = false
  let currentRunId = ''
  /** 本轮 llm_response 文本（轮内去重：turn_done 与已推送正文重复时不追加） */
  let turnTexts: string[] = []
  /** tool_use_id → messages 中待配对 tool 消息下标 */
  const pendingTools = new Map<string, number>()

  function clearReconnectTimer() {
    if (reconnectTimer) {
      clearTimeout(reconnectTimer)
      reconnectTimer = null
    }
  }

  // ── WS ──

  function connectWS(sessionId: string) {
    disconnectWS()
    const authStore = useAuthStore()
    const token = authStore.token || localStorage.getItem('auth-token') || ''
    if (!token) {
      lastError.value = '未找到认证 token，无法连接问答通道'
      return
    }
    const wsProtocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const wsUrl = `${wsProtocol}//${window.location.host}/api/chat/ws/${encodeURIComponent(sessionId)}`
    try {
      // 优先通过 Sec-WebSocket-Protocol 子协议传 token；失败时回退 ?token=
      ws = new WebSocket(wsUrl, ['bearer', token])
    } catch {
      ws = new WebSocket(`${wsUrl}?token=${encodeURIComponent(token)}`)
    }

    const socket = ws
    socket.onopen = () => {
      wsConnected.value = true
      reconnectAttempts = 0
    }
    socket.onmessage = (event) => {
      try {
        handleWSMessage(JSON.parse(event.data))
      } catch (error) {
        console.error('[ChatProcess] 解析消息失败:', error)
      }
    }
    socket.onerror = () => {
      wsConnected.value = false
    }
    socket.onclose = () => {
      wsConnected.value = false
      if (ws === socket) ws = null
      if (intentionalClose || currentSessionId.value !== sessionId) return
      // 指数退避重连，最多 10 次（与 analysisProcess 同款）
      if (reconnectAttempts < maxReconnectAttempts) {
        const delay = Math.min(1000 * Math.pow(2, reconnectAttempts), 30000)
        reconnectAttempts += 1
        reconnectTimer = setTimeout(() => connectWS(sessionId), delay)
      } else {
        lastError.value = '问答通道已断开且重连失败，请刷新页面重试'
      }
    }
  }

  function disconnectWS() {
    intentionalClose = true
    clearReconnectTimer()
    reconnectAttempts = 0
    if (ws) {
      try {
        ws.close()
      } catch {
        /* 忽略关闭错误 */
      }
      ws = null
    }
    wsConnected.value = false
  }

  function handleWSMessage(msg: ChatWSMessage) {
    switch (msg.type) {
      case 'connection_established':
        wsConnected.value = true
        break
      case 'stop_result':
      case 'pong':
        break
      case 'chat_event':
        handleChatEvent(msg)
        break
      default:
        break
    }
  }

  function handleChatEvent(msg: ChatWSMessage) {
    const evType = msg.event_type || ''
    const p = msg.payload ?? {}
    switch (evType) {
      case 'text_delta': {
        const text = typeof p.text === 'string' ? p.text : ''
        if (text) streamingText.value += text
        break
      }
      case 'thinking_delta': {
        const text = typeof p.text === 'string' ? p.text : ''
        if (text) streamingThinking.value += text
        break
      }
      case 'thinking': {
        // 聚合思考事件：清空流式态并落为消息气泡
        streamingThinking.value = ''
        const text = typeof p.text === 'string' ? p.text : ''
        if (text) {
          messages.value.push({ kind: 'thinking', id: `ev:${msg.seq}`, text })
        }
        break
      }
      case 'tool_call': {
        const name =
          typeof p.tool === 'string' ? p.tool : typeof p.name === 'string' ? p.name : 'unknown_tool'
        const toolUseId = typeof p.tool_use_id === 'string' ? p.tool_use_id : ''
        messages.value.push({
          kind: 'tool',
          id: `ev:${msg.seq}`,
          name,
          input: truncateText(p.input ?? p.arguments ?? p.parameters ?? ''),
          output: '',
          durationMs: null,
          isError: false,
          toolUseId: toolUseId || null,
          hasResult: false,
          isSubmission: false,
          submissionContent: ''
        })
        if (toolUseId) pendingTools.set(toolUseId, messages.value.length - 1)
        break
      }
      case 'tool_result': {
        const name =
          typeof p.tool === 'string' ? p.tool : typeof p.name === 'string' ? p.name : 'unknown_tool'
        const toolUseId = typeof p.tool_use_id === 'string' ? p.tool_use_id : ''
        const result = {
          output: truncateText(p.output ?? p.result ?? ''),
          durationMs: typeof p.duration_ms === 'number' ? p.duration_ms : null,
          isError: p.is_error === true,
          hasResult: true
        }
        let idx = toolUseId ? pendingTools.get(toolUseId) : undefined
        if (idx === undefined) {
          // 无 id 兜底：找最后一条同名且无结果的 tool 消息
          for (let i = messages.value.length - 1; i >= 0; i--) {
            const m = messages.value[i]
            if (m.kind === 'tool' && m.name === name && !m.hasResult) {
              idx = i
              break
            }
          }
        }
        const target = idx !== undefined ? messages.value[idx] : undefined
        if (idx !== undefined && target && target.kind === 'tool') {
          Object.assign(target, result)
          if (toolUseId) pendingTools.delete(toolUseId)
        } else {
          messages.value.push({
            kind: 'tool',
            id: `ev:${msg.seq}`,
            name,
            input: '',
            ...result,
            toolUseId: toolUseId || null,
            isSubmission: false,
            submissionContent: ''
          })
        }
        break
      }
      case 'llm_response': {
        // 非纯工具轮：正文落为气泡；纯工具轮 text 为空串，跳过
        const text = typeof p.text === 'string' ? p.text : ''
        streamingText.value = ''
        if (text) {
          turnTexts.push(text)
          messages.value.push({ kind: 'assistant', id: `ev:${msg.seq}`, text, missing: false })
        }
        break
      }
      case 'turn_done': {
        const finalText = typeof msg.assistant_text === 'string' ? msg.assistant_text : ''
        const joined = turnTexts.join('\n\n')
        const last = turnTexts[turnTexts.length - 1]
        // 与本轮已推送正文重复时不追加（run_conversation final_text 与轮内文本一致）
        if (finalText && finalText !== joined && finalText !== last) {
          messages.value.push({ kind: 'assistant', id: `done:${msg.run_id}`, text: finalText, missing: false })
        }
        finishTurn()
        break
      }
      case 'turn_failed': {
        const errText = typeof msg.error === 'string' ? msg.error : '回答生成失败'
        messages.value.push({ kind: 'error', id: `err:${msg.run_id}`, text: errText })
        finishTurn()
        break
      }
      case 'turn_cancelled': {
        const partial = typeof msg.assistant_text === 'string' ? msg.assistant_text : ''
        if (partial) {
          messages.value.push({ kind: 'assistant', id: `cancel:${msg.run_id}`, text: partial, missing: false })
        }
        finishTurn()
        break
      }
      default:
        // status 等过程事件不进消息流
        break
    }
  }

  function finishTurn() {
    running.value = false
    currentRunId = ''
    streamingText.value = ''
    streamingThinking.value = ''
    turnTexts = []
    pendingTools.clear()
  }

  // ── 会话与消息 actions ──

  async function loadSessions() {
    const resp = await chatApi.listSessions(1, 50)
    sessions.value = resp.data.sessions
  }

  /** 历史消息回放（chat_messages 只存 user/assistant 文本） */
  function backfillMessages(docs: ChatMessageDoc[]) {
    const out: UIMessage[] = []
    docs.forEach((d, i) => {
      if (d.role === 'user') {
        out.push({ kind: 'user', id: `db:${i}`, text: d.content, local: false })
      } else {
        out.push({ kind: 'assistant', id: `db:${i}`, text: d.content, missing: false })
      }
    })
    messages.value = out
  }

  /** 切换会话：断开旧 WS → 回放历史 → 连新 WS */
  async function loadSession(sessionId: string) {
    if (currentSessionId.value === sessionId && wsConnected.value) return
    disconnectWS()
    finishTurn()
    currentSessionId.value = sessionId
    messages.value = []
    lastError.value = ''
    const resp = await chatApi.getSession(sessionId)
    backfillMessages(resp.data.messages)
    connectWS(sessionId)
  }

  async function createSession() {
    const resp = await chatApi.createSession()
    await loadSessions()
    const created = sessions.value.find((s) => s.session_id === resp.data.session_id)
    await loadSession(resp.data.session_id)
    return created
  }

  async function deleteSession(sessionId: string) {
    await chatApi.deleteSession(sessionId)
    if (currentSessionId.value === sessionId) {
      disconnectWS()
      finishTurn()
      currentSessionId.value = ''
      messages.value = []
    }
    await loadSessions()
  }

  /** 发送一条消息（202 异步；回答经 WS 推送）。失败返回错误文案 */
  async function sendMessage(content: string): Promise<string | null> {
    const trimmed = content.trim()
    if (!trimmed) return '消息不能为空'
    if (!currentSessionId.value) return '请先选择或创建会话'
    if (running.value) return '当前会话正在回答，请等待完成或先停止'

    let resp
    try {
      resp = await chatApi.sendMessage(currentSessionId.value, trimmed)
    } catch (error: unknown) {
      const e = error as { response?: { status?: number; data?: { detail?: string } } }
      const status = e?.response?.status
      const detail = e?.response?.data?.detail
      if (status === 503) {
        chatEnabled.value = false
        return 'AI 问答助手未启用，请联系管理员在系统设置中开启'
      }
      if (status === 429) {
        return detail || '今日问答配额已用完'
      }
      if (status === 409) {
        return detail || '该会话正在回答上一条问题'
      }
      return detail || '发送失败，请稍后重试'
    }

    // 乐观用户消息；轮内事件流紧随其后
    messages.value.push({
      kind: 'user',
      id: `local:${(localSeq -= 1)}`,
      text: trimmed,
      local: true
    })
    running.value = true
    currentRunId = resp.data.run_id
    streamingText.value = ''
    streamingThinking.value = ''
    turnTexts = []
    pendingTools.clear()
    quotaRemaining.value = resp.data.quota_remaining
    return null
  }

  async function stop() {
    if (!currentRunId) return
    try {
      await chatApi.stopRun(currentRunId)
    } catch {
      // 停止失败不影响轮次（turn_cancelled / 超时兜底）
    }
  }

  async function refreshQuota() {
    try {
      const resp = await chatApi.getQuota()
      quotaRemaining.value = resp.data.quota_remaining
    } catch {
      // 配额查询失败不阻塞页面
    }
  }

  return {
    sessions,
    currentSessionId,
    messages,
    wsConnected,
    running,
    streamingText,
    streamingThinking,
    quotaRemaining,
    chatEnabled,
    lastError,
    loadSessions,
    loadSession,
    createSession,
    deleteSession,
    sendMessage,
    stop,
    refreshQuota,
    disconnectWS
  }
})
