import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { analysisApi, type AgentEvent } from '@/api/analysis'
import { useAuthStore } from '@/stores/auth'
import { buildChatMessages, type ChatMessage } from '@/components/Analysis/ChatTimeline/buildChatMessages'

export { buildChatMessages }
export type { ChatMessage }

/** report_ready 事件产物：智能体完成时生成的报告（按到达序） */
export interface AgentReport {
  key: string
  title: string
  content: string
}

/** 计数式实时进度（来自 agent_event 流中的 progress 事件，完成驱动） */
export interface ProgressInfo {
  completed: number
  total: number
  percent: number
  stepText: string
}

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

/** 本地乐观添加的用户消息 seq 固定为负数，避免与服务器 seq 冲突 */
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
  /** 计数式实时进度（WS progress 事件驱动；5s 轮询值在 TaskDetail 侧兜底） */
  const progressInfo = ref<ProgressInfo | null>(null)
  /** report_ready 产物（智能体实时报告），按到达序，report_key 去重 */
  const reports = ref<AgentReport[]>([])
  const seenReportKeys = new Set<string>()

  // ── 渲染窗口 state ──
  /** 渲染窗口大小：store.events 全量保存，每个 agent 各取最近 RENDER_WINDOW 条（per-agent 窗口，
   * 避免全局窗口把事件少的 agent 历史整段切掉） */
  const RENDER_WINDOW = 500
  /** agent_key → 实时流式文本（live 模式 text_delta 累积，收到 llm_response 清空） */
  const streamingText = ref<Record<string, string>>({})
  /** agent_key → 实时流式思考（live 模式 thinking_delta 累积，收到聚合 thinking 事件清空） */
  const streamingThinking = ref<Record<string, string>>({})
  /** 是否还有更早的事件可加载（loadEarlier 向前分页拉取） */
  const hasMoreEarlier = ref(false)
  /**
   * 乐观用户消息（seq<0）单独存放，不混入 events：
   * 避免被渲染窗口 slice 切掉；visibleEvents 计算时合并到窗口尾部。
   * 收到服务器 user_message_injected 真实回显后移除对应乐观消息。
   */
  const pendingMessages = ref<AgentEvent[]>([])
  /** 已入库事件去重键（`agent_key:seq`），重连重放时 O(1) 判重 */
  const seenEventKeys = new Set<string>()

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

  /**
   * per-agent 渲染窗口：每个 agent 各取最近 RENDER_WINDOW 条（events 已按 seq 升序）；
   * 乐观消息（pendingMessages，seq<0）不参与窗口裁剪，合并到对应 agent 窗口尾部。
   */
  const visibleEventsByAgent = computed(() => {
    const byAgent = new Map<string, AgentEvent[]>()
    for (const ev of events.value) {
      const list = byAgent.get(ev.agent_key)
      if (list) list.push(ev)
      else byAgent.set(ev.agent_key, [ev])
    }
    const windowed = new Map<string, AgentEvent[]>()
    for (const [key, list] of byAgent) {
      const cut = list.length > RENDER_WINDOW ? list.slice(list.length - RENDER_WINDOW) : list
      windowed.set(key, cut)
    }
    for (const p of pendingMessages.value) {
      const list = windowed.get(p.agent_key) ?? []
      list.push(p)
      windowed.set(p.agent_key, list)
    }
    return windowed
  })

  /** 是否还有更早的事件可加载（per-agent 判断：全局游标未拉完，或该 agent 自身窗口被裁剪） */
  function hasMoreEarlierFor(agentKey: string): boolean {
    if (hasMoreEarlier.value) return true
    const list = visibleEventsByAgent.value.get(agentKey)
    return !!list && list.length >= RENDER_WINDOW
  }

  /** 各 agent 对话消息序列（事件流 → ChatMessage[]，纯函数 buildChatMessages 的 computed 缓存） */
  const chatTimelines = computed(() => {
    const map = new Map<string, ChatMessage[]>()
    for (const [key, evs] of visibleEventsByAgent.value) map.set(key, buildChatMessages(evs))
    return map
  })

  // ── 内部工具 ──
  function ensureAgent(key: string) {
    if (!agentOrder.value.includes(key)) {
      agentOrder.value.push(key)
      agentStatus.value[key] = 'running'
    }
  }

  /** 二分插入：events 全部为服务器事件（seq>=0）且按 seq 升序，避免每次整体 sort 的 O(n log n) */
  function insertEvent(ev: AgentEvent) {
    if (ev.seq >= 0) {
      const key = `${ev.agent_key}:${ev.seq}`
      if (seenEventKeys.has(key)) return
      seenEventKeys.add(key)
    }
    const evs = events.value
    let lo = 0
    let hi = evs.length
    while (lo < hi) {
      const mid = (lo + hi) >> 1
      if (evs[mid].seq <= ev.seq) lo = mid + 1
      else hi = mid
    }
    evs.splice(lo, 0, ev)
  }

  /** 批量插入（loadReplay / loadEarlier）：Set 判重后整批 concat 一次排序，代替逐条二分 splice */
  function insertEvents(batch: AgentEvent[]) {
    if (batch.length === 0) return
    const fresh = batch.filter(ev => {
      if (ev.seq < 0) return true
      const key = `${ev.agent_key}:${ev.seq}`
      if (seenEventKeys.has(key)) return false
      seenEventKeys.add(key)
      return true
    })
    if (fresh.length === 0) return
    events.value = [...events.value, ...fresh].sort((a, b) => a.seq - b.seq)
  }

  /**
   * 应用一条 agent 事件的副作用（状态/标签/乐观消息回执清理）。
   * @param insert true 时同时入库（去重由 insertEvent/insertEvents 的 Set 保证）
   */
  function applyAgentEvent(ev: AgentEvent, insert = true) {
    // progress 事件只更新 progressInfo，不建 agent tab（防御：正常路径已在 handleWSMessage 提前返回）
    if (ev.event_type === 'progress') return
    ensureAgent(ev.agent_key)
    if (insert) insertEvent(ev)
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
      const idx = pendingMessages.value.findIndex(p =>
        p.agent_key === ev.agent_key
        && echoText.includes(String((p.payload as Record<string, unknown> | undefined)?.text ?? '\x00')),
      )
      if (idx >= 0) pendingMessages.value.splice(idx, 1)
    } else if (ev.event_type === 'report_ready') {
      // 智能体报告就绪：按 report_key 去重、按到达序追加（WS 实时与回放重建共用此路径）
      const p = (ev.payload ?? {}) as Record<string, unknown>
      const key = typeof p.report_key === 'string' && p.report_key
        ? p.report_key
        : `${ev.agent_key}:${ev.seq}`
      if (!seenReportKeys.has(key)) {
        seenReportKeys.add(key)
        reports.value.push({
          key,
          title: typeof p.title === 'string' && p.title ? p.title : key,
          content: typeof p.content === 'string' ? p.content : '',
        })
      }
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
        // thinking_delta 同构：不落库不入 events，累积到 streamingThinking 实时渲染
        if (msg.event_type === 'thinking_delta') {
          const delta = String((msg.payload as Record<string, unknown> | undefined)?.text ?? '')
          if (delta) streamingThinking.value[msg.agent_key] = (streamingThinking.value[msg.agent_key] ?? '') + delta
          return
        }
        // status 阶段提示（如"正在生成最终交易信号..."）：只更新进度文案，
        // 不入 events、不建 agent tab
        if (msg.event_type === 'status') {
          const text = String((msg.payload as Record<string, unknown> | undefined)?.text ?? '')
          if (text && progressInfo.value) progressInfo.value = { ...progressInfo.value, stepText: text }
          return
        }
        // 计数式进度（完成驱动）：只更新 progressInfo，不入 events、不建 agent tab
        if (msg.event_type === 'progress') {
          const p = (msg.payload ?? {}) as Record<string, unknown>
          const percent = Number(p.percent ?? 0)
          progressInfo.value = {
            completed: Number(p.completed ?? 0),
            total: Number(p.total ?? 0),
            // 单调保护：乱序回退不下降
            percent: Math.max(progressInfo.value?.percent ?? 0, percent),
            stepText: typeof p.step_text === 'string' ? p.step_text : '',
          }
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
        // llm_response 到达后流式文本已固化；聚合 thinking 到达后流式思考固化；
        // agent_end 兜底清空，避免残留实时气泡
        if (msg.event_type === 'llm_response' || msg.event_type === 'agent_end') {
          delete streamingText.value[msg.agent_key]
        }
        if (msg.event_type === 'thinking' || msg.event_type === 'agent_end') {
          delete streamingThinking.value[msg.agent_key]
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
      // 本地乐观添加高亮消息：存 pendingMessages（seq<0），不混入 events 以免被渲染窗口切掉
      localSeq -= 1
      pendingMessages.value.push({
        task_id: taskId.value,
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
      // 分页拉全量：先整批收集，再一次 insertEvents 排序入库（避免逐条插入的重复 splice）
      const all: AgentEvent[] = []
      // eslint-disable-next-line no-constant-condition
      while (true) {
        const res = await analysisApi.getTaskEvents(id, { after_seq: afterSeq, limit: 500 })
        const list: AgentEvent[] = res?.data ?? []
        all.push(...list)
        if (list.length < 500) break
        afterSeq = list[list.length - 1].seq
      }
      insertEvents(all)
      for (const ev of all) applyAgentEvent(ev, false)
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

  /**
   * 详情页 running 主入口：先连 WS 再 desc 首拉回填历史。
   * 顺序约束：start() 内部会 stop()+reset() 清空 events，因此回放填充必须放在 start() 之后；
   * WS 与回填并发到达时由 insertEvent/insertEvents 的 seenEventKeys 去重无缝拼接。
   */
  async function loadLatestAndConnect(id: string) {
    lastError.value = '' // 必须在 start() 之前清空：start 连接失败会写入 WS 错误，不能被覆盖
    start(id) // 连 WS（此后 WS 增量事件正常进入）
    loadingReplay.value = true
    try {
      // desc 首拉最近 500 条，reverse 为升序后入库（副作用需按时间正序应用）
      const res = await analysisApi.getTaskEvents(id, { order: 'desc', limit: 500 })
      const list: AgentEvent[] = res?.data ?? []
      if (list.length > 0) {
        const ordered = list.slice().reverse()
        insertEvents(ordered)
        for (const ev of ordered) applyAgentEvent(ev, false)
      }
      hasMoreEarlier.value = list.length >= 500
      // 补洞：空洞在 desc 快照尾与 WS 首个增量之间，必须以快照自身的最大 seq
      // （desc 首条）为锚升序补拉；用 events 末尾 seq 会跳过最需要补的区间。
      // 与 WS 并发达到的重复事件由 seenEventKeys 去重吸收。
      const snapshotMaxSeq = list.length > 0 ? list[0].seq : 0
      const inc = await analysisApi.getTaskEvents(id, { after_seq: snapshotMaxSeq, limit: 500 })
      const incList: AgentEvent[] = inc?.data ?? []
      if (incList.length > 0) {
        insertEvents(incList)
        for (const ev of incList) applyAgentEvent(ev, false)
      }
    } catch (error) {
      console.error('[AnalysisProcess] 加载最新事件失败:', error)
      lastError.value = '加载历史事件失败'
    } finally {
      loadingReplay.value = false
    }
  }

  /** 加载更早的事件：以当前 events 最小 seq 为锚，向前分页拉取（desc → reverse 升序） */
  async function loadEarlier() {
    const evs = events.value
    if (!taskId.value || evs.length === 0) {
      hasMoreEarlier.value = false
      return
    }
    try {
      const res = await analysisApi.getTaskEvents(taskId.value, {
        order: 'desc',
        before_seq: evs[0].seq,
        limit: 500,
      })
      const list: AgentEvent[] = res?.data ?? []
      if (list.length > 0) {
        // 副作用必须按时间正序应用：desc 原序会让 agent_end 先于 agent_start，
        // 把已完成 agent 翻回 running
        const ordered = list.slice().reverse()
        insertEvents(ordered)
        for (const ev of ordered) applyAgentEvent(ev, false)
      }
      if (list.length < 500) hasMoreEarlier.value = false
    } catch (error) {
      console.error('[AnalysisProcess] 加载更早事件失败:', error)
      lastError.value = '加载更早事件失败'
    }
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
    streamingThinking.value = {}
    hasMoreEarlier.value = false
    pendingMessages.value = []
    reports.value = []
    progressInfo.value = null
    seenReportKeys.clear()
    seenEventKeys.clear()
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
    streamingThinking,
    hasMoreEarlier,
    pendingMessages,
    reports,
    progressInfo,
    agents,
    anyRunning,
    visibleEventsByAgent,
    chatTimelines,
    hasMoreEarlierFor,
    start,
    stop,
    sendAgentMessage,
    loadLatestAndConnect,
    loadReplay,
    loadEarlier,
    reset,
  }
})
