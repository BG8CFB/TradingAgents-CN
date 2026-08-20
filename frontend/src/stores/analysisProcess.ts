import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { analysisApi, type AgentEvent } from '@/api/analysis'
import { useAuthStore } from '@/stores/auth'

/** agent 执行状态 */
export type AgentRunStatus = 'running' | 'completed'

/** sendAgentMessage 的回执 */
export interface AgentMessageReceipt {
  ok: boolean
  reason?: string
  runningAgents?: string[]
}

/** 面板整体模式 */
export type ProcessMode = 'idle' | 'live' | 'replay'

/** WS 下行消息（宽松解析） */
interface TaskWSMessage {
  type: string
  task_id?: string
  seq?: number
  ts?: number | string
  phase?: string
  agent_key?: string
  event_type?: string
  payload?: Record<string, unknown>
  reason?: string
  running_agents?: string[]
  [key: string]: unknown
}

/** 本地乐观添加的用户消息事件 seq 固定为负数，避免与服务器 seq 冲突 */
let localSeq = -1

export const useAnalysisProcessStore = defineStore('analysisProcess', () => {
  // ── state ──
  const taskId = ref('')
  const mode = ref<ProcessMode>('idle')
  const connected = ref(false)
  const events = ref<AgentEvent[]>([])
  const agentOrder = ref<string[]>([])
  const agentStatus = ref<Record<string, AgentRunStatus>>({})
  const lastError = ref('')
  const loadingReplay = ref(false)

  // ── 渲染窗口 state（Task 5）──
  /** 渲染窗口大小：store.events 全量保存，visibleEvents 只暴露最近 RENDER_WINDOW 条 */
  const RENDER_WINDOW = 500
  /** agent_key → 实时流式文本（live 模式 text_delta 累积，收到 llm_response 清空） */
  const streamingText = ref<Record<string, string>>({})
  /** 是否还有更早的事件可加载（loadEarlier 拉取，Task 6 实现真实逻辑） */
  const hasMoreEarlier = ref(false)

  // ── WS 内部状态 ──
  let ws: WebSocket | null = null
  let reconnectTimer: ReturnType<typeof setTimeout> | null = null
  let reconnectAttempts = 0
  const maxReconnectAttempts = 10
  let intentionalClose = false
  /** 等待 user_message 回执的 resolver，按 agent_key 串行（同一 agent 同时只挂一条） */
  const pendingReceipts = new Map<string, (r: AgentMessageReceipt) => void>()

  // ── getters ──
  /** agent_key → 显示名（来自 agent_start 事件的 payload.name，缺省用 key） */
  const agentLabels = ref<Record<string, string>>({})

  /** 按执行顺序聚合的 agent 列表 */
  const agents = computed(() =>
    agentOrder.value.map(key => ({
      key,
      label: agentLabels.value[key] ?? key,
      status: agentStatus.value[key] ?? 'running',
      events: events.value.filter(e => e.agent_key === key),
    })),
  )

  /** 是否有任一 agent 还在运行 */
  const anyRunning = computed(() =>
    agentOrder.value.some(key => (agentStatus.value[key] ?? 'running') === 'running'),
  )

  /** 渲染窗口：events 已按 seq 升序，取最近 RENDER_WINDOW 条（本地乐观 seq<0 消息天然保留在窗口内） */
  const visibleEvents = computed(() => {
    const evs = events.value
    return evs.length > RENDER_WINDOW ? evs.slice(evs.length - RENDER_WINDOW) : [...evs]
  })

  /** 基于 visibleEvents 的 agent 执行顺序（只渲染窗口内出现过的 agent） */
  const visibleAgentOrder = computed(() => {
    const seen = new Set(visibleEvents.value.map(e => e.agent_key))
    return agentOrder.value.filter(key => seen.has(key))
  })

  // ── 内部工具 ──
  function ensureAgent(key: string) {
    if (!agentOrder.value.includes(key)) {
      agentOrder.value.push(key)
      agentStatus.value[key] = 'running'
    }
  }

  function insertEvent(ev: AgentEvent) {
    // 按 seq 升序插入（本地乐观消息 seq<0 排最前亦可，直接排序即可）
    events.value.push(ev)
    events.value.sort((a, b) => a.seq - b.seq)
  }

  function applyAgentEvent(ev: AgentEvent) {
    ensureAgent(ev.agent_key)
    // 去重（重连后可能收到重复消息）
    if (events.value.some(e => e.seq === ev.seq && e.agent_key === ev.agent_key && e.seq >= 0)) return
    insertEvent(ev)
    if (ev.event_type === 'agent_end') {
      agentStatus.value[ev.agent_key] = 'completed'
    } else if (ev.event_type === 'agent_start') {
      // 重连回放场景下 agent 可能重新开始
      agentStatus.value[ev.agent_key] = 'running'
      const name = (ev.payload as Record<string, unknown> | undefined)?.name
      if (typeof name === 'string' && name) agentLabels.value[ev.agent_key] = name
    } else if (ev.event_type === 'user_message_injected' && ev.seq >= 0) {
      // 真实回显到达：移除对应的本地乐观消息（回显为 system-reminder 包装，含用户原文）
      const echoText = String((ev.payload as Record<string, unknown> | undefined)?.text ?? '')
      const idx = events.value.findIndex(e =>
        e.seq < 0 && e.agent_key === ev.agent_key
        && e.event_type === 'user_message_injected'
        && echoText.includes(String((e.payload as Record<string, unknown> | undefined)?.text ?? '\x00')),
      )
      if (idx >= 0) events.value.splice(idx, 1)
    }
  }

  function handleWSMessage(raw: unknown) {
    if (raw === null || typeof raw !== 'object') return
    const msg = raw as TaskWSMessage
    switch (msg.type) {
      case 'connection_established':
        connected.value = true
        break
      case 'agent_event': {
        if (!msg.agent_key || typeof msg.seq !== 'number') return
        // text_delta 不落库也不入 events，仅累积到 streamingText 供实时渲染
        if (msg.event_type === 'text_delta') {
          const delta = String((msg.payload as Record<string, unknown> | undefined)?.text ?? '')
          if (delta) streamingText.value[msg.agent_key] = (streamingText.value[msg.agent_key] ?? '') + delta
          return
        }
        applyAgentEvent({
          task_id: typeof msg.task_id === 'string' ? msg.task_id : taskId.value,
          seq: msg.seq,
          ts: msg.ts,
          phase: typeof msg.phase === 'string' ? msg.phase : undefined,
          agent_key: msg.agent_key,
          event_type: msg.event_type ?? '',
          payload: msg.payload,
        })
        // llm_response 到达后流式文本已固化，清空实时气泡
        if (msg.event_type === 'llm_response') {
          delete streamingText.value[msg.agent_key]
        }
        break
      }
      case 'user_message_injected': {
        const resolve = msg.agent_key ? pendingReceipts.get(msg.agent_key) : undefined
        if (msg.agent_key) pendingReceipts.delete(msg.agent_key)
        resolve?.({ ok: true })
        break
      }
      case 'user_message_rejected': {
        const resolve = msg.agent_key ? pendingReceipts.get(msg.agent_key) : undefined
        if (msg.agent_key) pendingReceipts.delete(msg.agent_key)
        resolve?.({
          ok: false,
          reason: typeof msg.reason === 'string' ? msg.reason : '消息被拒绝',
          runningAgents: Array.isArray(msg.running_agents) ? msg.running_agents : [],
        })
        break
      }
      case 'progress_update':
        // 原有进度消息，忽略
        break
      default:
        break
    }
  }

  function clearReconnectTimer() {
    if (reconnectTimer) {
      clearTimeout(reconnectTimer)
      reconnectTimer = null
    }
  }

  function connectWS() {
    if (!taskId.value) return
    const authStore = useAuthStore()
    const token = authStore.token || localStorage.getItem('auth-token') || ''
    if (!token) {
      lastError.value = '未找到认证 token，无法连接分析过程'
      return
    }

    const wsProtocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const wsUrl = `${wsProtocol}//${window.location.host}/api/analysis/ws/task/${taskId.value}`
    try {
      // 优先通过 Sec-WebSocket-Protocol 子协议传递 token；失败时回退 ?token=
      ws = new WebSocket(wsUrl, ['bearer', token])
    } catch {
      ws = new WebSocket(`${wsUrl}?token=${encodeURIComponent(token)}`)
    }

    const socket = ws
    socket.onopen = () => {
      connected.value = true
      reconnectAttempts = 0
    }
    socket.onmessage = (event) => {
      try {
        handleWSMessage(JSON.parse(event.data))
      } catch (error) {
        console.error('[AnalysisProcess] 解析消息失败:', error)
      }
    }
    socket.onerror = () => {
      connected.value = false
    }
    socket.onclose = () => {
      connected.value = false
      if (ws === socket) ws = null
      if (intentionalClose || mode.value !== 'live') return
      // 指数退避重连，最多 10 次
      if (reconnectAttempts < maxReconnectAttempts) {
        const delay = Math.min(1000 * Math.pow(2, reconnectAttempts), 30000)
        reconnectAttempts += 1
        reconnectTimer = setTimeout(() => connectWS(), delay)
      } else {
        lastError.value = '连接已断开且重连失败，请刷新或稍后重试'
      }
    }
  }

  // ── actions ──

  /** 连接任务 WS，实时跟踪分析过程 */
  function start(id: string) {
    stop()
    reset()
    taskId.value = id
    mode.value = 'live'
    intentionalClose = false
    reconnectAttempts = 0
    connectWS()
  }

  /** 断开 WS 并停止跟踪（保留已收到的事件供查看） */
  function stop() {
    intentionalClose = true
    clearReconnectTimer()
    reconnectAttempts = 0
    if (ws) {
      try { ws.close() } catch { /* 忽略关闭错误 */ }
      ws = null
    }
    connected.value = false
    // 未收到回执的挂起 promise 一律按失败结清
    pendingReceipts.forEach((resolve, key) => {
      pendingReceipts.delete(key)
      resolve({ ok: false, reason: '连接已断开' })
    })
    if (mode.value === 'live') mode.value = 'idle'
  }

  /** 向正在运行的 agent 注入用户消息（返回回执 promise） */
  function sendAgentMessage(agentKey: string, text: string): Promise<AgentMessageReceipt> {
    const trimmed = text.trim()
    if (!trimmed) {
      return Promise.resolve({ ok: false, reason: '消息不能为空' })
    }
    if (!ws || ws.readyState !== WebSocket.OPEN) {
      return Promise.resolve({ ok: false, reason: '连接未就绪，无法发送消息' })
    }
    if ((agentStatus.value[agentKey] ?? 'running') !== 'running') {
      return Promise.resolve({ ok: false, reason: '该智能体已完成，无法接收消息' })
    }
    return new Promise<AgentMessageReceipt>((resolve) => {
      pendingReceipts.set(agentKey, resolve)
      ws!.send(JSON.stringify({ type: 'user_message', agent_key: agentKey, text: trimmed }))
      // 本地乐观添加高亮消息
      localSeq -= 1
      insertEvent({
        seq: localSeq,
        ts: new Date().toISOString(),
        agent_key: agentKey,
        event_type: 'user_message_injected',
        payload: { text: trimmed, local: true },
      })
      // 超时兜底：30s 未收到回执
      setTimeout(() => {
        const settle = pendingReceipts.get(agentKey)
        if (settle) {
          pendingReceipts.delete(agentKey)
          settle({ ok: false, reason: '等待回执超时' })
        }
      }, 30000)
    })
  }

  /** 回放模式：从 HTTP 拉取全量事件填充（不连 WS） */
  async function loadReplay(id: string) {
    taskId.value = id
    mode.value = 'replay'
    loadingReplay.value = true
    lastError.value = ''
    let afterSeq: number | undefined
    try {
      // 分页拉全量
      // eslint-disable-next-line no-constant-condition
      while (true) {
        const res = await analysisApi.getTaskEvents(id, { after_seq: afterSeq, limit: 500 })
        const list: AgentEvent[] = res?.data ?? []
        for (const ev of list) applyAgentEvent(ev)
        if (list.length < 500) break
        afterSeq = list[list.length - 1].seq
      }
      // 回放时所有 agent 均已结束
      for (const key of agentOrder.value) agentStatus.value[key] = 'completed'
      // 回放拉全量：总数超出渲染窗口即可"加载更早"
      hasMoreEarlier.value = events.value.length > RENDER_WINDOW
    } catch (error) {
      console.error('[AnalysisProcess] 加载回放事件失败:', error)
      lastError.value = '加载分析过程失败'
    } finally {
      loadingReplay.value = false
    }
  }

  /** 加载更早的事件（拉取窗口之前的分页；真实拉取逻辑 Task 6 实现） */
  async function loadEarlier() {
    // Task 6: getTaskEvents(id, { order: 'desc', before_seq: visibleEvents 最小 seq, limit: 500 })
    return
  }

  /** 重置全部状态 */
  function reset() {
    taskId.value = ''
    mode.value = 'idle'
    connected.value = false
    events.value = []
    agentOrder.value = []
    agentStatus.value = {}
    agentLabels.value = {}
    lastError.value = ''
    localSeq = -1
    streamingText.value = {}
    hasMoreEarlier.value = false
    pendingReceipts.clear()
  }

  return {
    taskId,
    mode,
    connected,
    events,
    agentOrder,
    agentStatus,
    agentLabels,
    lastError,
    loadingReplay,
    streamingText,
    hasMoreEarlier,
    agents,
    anyRunning,
    visibleEvents,
    visibleAgentOrder,
    start,
    stop,
    sendAgentMessage,
    loadReplay,
    loadEarlier,
    reset,
  }
})
