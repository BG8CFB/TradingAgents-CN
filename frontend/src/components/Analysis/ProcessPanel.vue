<template>
  <div class="process-panel">
    <!-- 顶部总状态 -->
    <div class="process-header">
      <div class="process-header-left">
        <el-icon v-if="isLive && store.connected" class="status-icon status-live" :size="14"><Connection /></el-icon>
        <el-icon v-else-if="isLive" class="status-icon status-connecting" :size="14"><Loading /></el-icon>
        <el-icon v-else class="status-icon status-replay" :size="14"><VideoPlay /></el-icon>
        <span class="process-status-text">{{ statusText }}</span>
      </div>
      <div class="process-header-meta">
        <span class="meta-item">事件 {{ store.events.length }}</span>
        <span class="meta-item">token {{ formattedTokenCount }}</span>
      </div>
    </div>

    <el-alert
      v-if="store.lastError"
      :title="store.lastError"
      type="error"
      :closable="false"
      class="process-error"
    />

    <div v-if="store.agents.length === 0" class="process-empty">
      <el-empty :description="isEmptyText" :image-size="60" />
    </div>

    <!-- 主体：单一纵向事件流 -->
    <template v-else>
      <!-- 加载更早事件（渲染窗口外还有历史） -->
      <div v-if="store.hasMoreEarlier" class="load-earlier">
        <el-button size="small" text :loading="loadingEarlier" @click="onLoadEarlier">
          加载更早事件
        </el-button>
      </div>

      <div ref="streamEl" class="stream" @scroll="onScroll">
        <div
          v-for="agent in visibleAgents"
          :key="agent.key"
          class="agent-section"
          :class="{ 'is-running': agent.status === 'running' }"
        >
          <!-- 段头：状态 + 显示名 + 耗时，点击折叠/展开 -->
          <div class="agent-section-head" @click="toggleSection(agent.key)">
            <span class="agent-dot" :class="agent.status === 'running' ? 'is-running' : 'is-done'">●</span>
            <span class="agent-name" :title="agent.label">{{ agent.label }}</span>
            <span v-if="agent.status === 'running'" class="agent-state is-running">
              <el-icon class="is-spinning"><Loading /></el-icon>
              运行中
            </span>
            <span v-else class="agent-state is-done">
              <el-icon><CircleCheckFilled /></el-icon>
              <template v-if="agentDurations.get(agent.key) != null">{{ formatDuration(agentDurations.get(agent.key)!) }}</template>
              <template v-else>完成</template>
            </span>
            <el-icon class="section-caret" :class="{ expanded: isExpanded(agent.key) }"><ArrowRight /></el-icon>
          </div>

          <!-- 段内时间线 -->
          <div v-show="isExpanded(agent.key)" class="timeline">
            <template v-for="item in timelines.get(agent.key) ?? []" :key="item.id">
              <!-- assistant 文本（markdown 渲染） -->
              <div v-if="item.kind === 'assistant'" class="timeline-item assistant">
                <!-- eslint-disable-next-line vue/no-v-html -- DOMPurify 消毒后的 markdown HTML（memoize 缓存） -->
                <div class="bubble assistant-bubble md-bubble" v-html="cachedMarkdown(item.text)"></div>
              </div>

              <!-- 用户注入消息 -->
              <div v-else-if="item.kind === 'user'" class="timeline-item user">
                <div class="bubble user-bubble">
                  <span class="user-badge">用户注入</span>
                  <span class="user-text">{{ item.text }}</span>
                </div>
              </div>

              <!-- 工具调用折叠 -->
              <div v-else-if="item.kind === 'tool'" class="timeline-item tool">
                <div class="tool-item" :class="{ 'is-error': item.isError }">
                  <div class="tool-head" @click="toggleTool(item.id)">
                    <el-icon class="tool-expand-icon" :class="{ expanded: expandedTools[item.id] }"><ArrowRight /></el-icon>
                    <span class="tool-name">{{ item.name }}</span>
                    <span v-if="item.durationMs != null" class="tool-duration">{{ item.durationMs }}ms</span>
                    <el-tag v-if="item.isError" type="danger" size="small" effect="plain">错误</el-tag>
                  </div>
                  <div v-show="expandedTools[item.id]" class="tool-detail">
                    <div v-if="item.input" class="tool-block">
                      <div class="tool-block-label">参数</div>
                      <pre class="tool-pre">{{ item.input }}</pre>
                    </div>
                    <div v-if="item.output" class="tool-block">
                      <div class="tool-block-label">结果</div>
                      <pre class="tool-pre" :class="{ 'is-error-text': item.isError }">{{ item.output }}</pre>
                    </div>
                  </div>
                </div>
              </div>

              <!-- 压缩提示 -->
              <div v-else-if="item.kind === 'compact'" class="timeline-item compact">
                <div class="compact-bar">
                  <el-icon :size="12"><WarningFilled /></el-icon>
                  <span>{{ compactText(item.text) }}</span>
                </div>
              </div>
            </template>

            <!-- running agent 尾部：text_delta 实时气泡（独立小组件，delta 只重渲该组件） -->
            <StreamingBubble v-if="agent.status === 'running'" :agent-key="agent.key" />
          </div>
        </div>
      </div>

      <!-- 回到底部悬浮按钮 -->
      <transition name="fade">
        <button v-if="!atBottom" class="scroll-bottom-btn" type="button" @click="scrollToBottom(true)">
          ↓ 回到底部
        </button>
      </transition>

      <!-- 底部输入区：目标 agent 下拉（仅 running）+ 单输入框 -->
      <div v-if="isLive" class="agent-input-area">
        <div class="input-row">
          <el-select
            v-model="selectedAgent"
            size="small"
            class="agent-select"
            placeholder="选择智能体"
            :disabled="runningAgents.length === 0"
          >
            <el-option
              v-for="a in runningAgents"
              :key="a.key"
              :label="a.label"
              :value="a.key"
            />
          </el-select>
          <el-input
            v-model="inputText"
            size="small"
            :placeholder="inputPlaceholder"
            :disabled="!canSend || sending"
            @keyup.enter="sendMessage()"
          />
          <el-button
            size="small"
            type="primary"
            :loading="sending"
            :disabled="!canSend || sending"
            @click="sendMessage()"
          >
            发送
          </el-button>
        </div>
        <div v-if="runningAgents.length === 0" class="agent-input-disabled">
          暂无运行中的智能体，仅分析中的智能体可接收消息
        </div>
      </div>
    </template>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, computed, watch, onBeforeUnmount, nextTick } from 'vue'
import { ElMessage } from 'element-plus'
import { Connection, Loading, VideoPlay, CircleCheckFilled, ArrowRight, WarningFilled } from '@element-plus/icons-vue'
import { useAnalysisProcessStore } from '@/stores/analysisProcess'
import { renderMarkdown } from '@/utils/markdown'
import type { AgentEvent } from '@/api/analysis'
import StreamingBubble from './StreamingBubble.vue'

const props = defineProps<{
  /** 任务 ID（live 模式下可缺省，由父组件先 store.start()） */
  taskId?: string
  /** 回放模式：通过 HTTP 拉取全量事件，不连 WS */
  replay?: boolean
}>()

const store = useAnalysisProcessStore()

const isLive = computed(() => !props.replay)
const statusText = computed(() => {
  if (props.replay) return store.loadingReplay ? '回放加载中...' : '回放模式'
  if (!store.connected) return '连接中...'
  return store.anyRunning ? '分析运行中' : '已完成'
})
const isEmptyText = computed(() =>
  props.replay ? (store.loadingReplay ? '正在加载分析过程...' : '该任务暂无过程事件') : '等待智能体事件...',
)

/** token 用量统计（求和所有 llm_response 的 input_tokens + output_tokens） */
const formattedTokenCount = computed(() => {
  let total = 0
  for (const ev of store.events) {
    if (ev.event_type !== 'llm_response') continue
    const p = (ev.payload ?? {}) as Record<string, unknown>
    const input = typeof p.input_tokens === 'number' ? p.input_tokens : 0
    const output = typeof p.output_tokens === 'number' ? p.output_tokens : 0
    total += input + output
  }
  return total >= 10000 ? `${(total / 1000).toFixed(1)}k` : String(total)
})

// ── 段落折叠 ──
/** 用户手动展开/折叠状态：存在即覆盖自动策略（running 展开 / 完成折叠） */
const manualExpanded = reactive<Record<string, boolean>>({})

function isExpanded(agentKey: string): boolean {
  const key = agentKey as keyof typeof manualExpanded
  if (key in manualExpanded) return manualExpanded[key]
  return (store.agentStatus[agentKey] ?? 'running') === 'running'
}

function toggleSection(agentKey: string) {
  manualExpanded[agentKey] = !isExpanded(agentKey)
}

// ── 渲染窗口内的 agent 列表 ──
const visibleAgents = computed(() =>
  store.visibleAgentOrder.map(key => ({
    key,
    label: store.agentLabels[key] ?? key,
    status: store.agentStatus[key] ?? 'running',
  })),
)

/** agent 耗时 Map（首条事件 → 末条事件，无 ts 的 agent 不在 Map 中）：computed 缓存，避免模板每渲染逐 agent filter */
const agentDurations = computed(() => {
  const map = new Map<string, number>()
  for (const agentKey of store.visibleAgentOrder) {
    const evs = store.visibleEvents.filter(e => e.agent_key === agentKey && e.ts != null)
    if (evs.length === 0) continue
    const first = Date.parse(String(evs[0].ts))
    const last = Date.parse(String(evs[evs.length - 1].ts))
    if (Number.isNaN(first) || Number.isNaN(last) || last < first) continue
    map.set(agentKey, last - first)
  }
  return map
})

function formatDuration(ms: number): string {
  if (ms < 1000) return `${ms}ms`
  if (ms < 60000) return `${(ms / 1000).toFixed(1)}s`
  const m = Math.floor(ms / 60000)
  const s = Math.round((ms % 60000) / 1000)
  return `${m}m${s}s`
}

// 实时流式文本（text_delta 累积）由 StreamingBubble 子组件直接读 store，父组件不再建立渲染依赖

// ── 时间线视图模型 ──
interface ToolTimelineItem {
  kind: 'tool'
  id: string
  name: string
  input: string
  output: string
  durationMs: number | null
  isError: boolean
}
interface TextTimelineItem {
  kind: 'assistant' | 'user' | 'compact'
  id: string
  text: string
}
type TimelineItem = ToolTimelineItem | TextTimelineItem

/** 工具行展开状态（按事件 id 持久，避免重建时间线时丢失） */
const expandedTools = reactive<Record<string, boolean>>({})

function toggleTool(id: string) {
  expandedTools[id] = !expandedTools[id]
}

/** 截断 JSON 文本用于展示 */
function truncate(value: unknown, max = 400): string {
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
  return text.length > max ? `${text.slice(0, max)}...(截断)` : text
}

function payloadText(p: Record<string, unknown> | undefined): string {
  if (!p) return ''
  const text = p.text ?? p.summary ?? p.output
  return typeof text === 'string' ? text : ''
}

/** 从 system-reminder 包装中提取用户原文（回放事件的落库全文） */
function extractUserText(raw: string): string {
  const m = raw.match(/while you were working:\s*([\s\S]*?)\s*\n\s*IMPORTANT:/)
  return m ? m[1].trim() : raw
}

/**
 * compact 行文案。事件真实字段为 level（auto/reactive）+ messages（条数），
 * 若上游补充 before_tokens/after_tokens 则展示 token 收缩。
 */
function compactText(raw: string): string {
  let p: Record<string, unknown> = {}
  try {
    p = raw ? (JSON.parse(raw) as Record<string, unknown>) : {}
  } catch {
    p = {}
  }
  const level = typeof p.level === 'string' ? p.level : ''
  const messages = typeof p.messages === 'number' ? p.messages : null
  const before = p.before_tokens ?? p.tokens_before
  const after = p.after_tokens ?? p.tokens_after
  let text = '上下文压缩'
  if (level) text += `（${level}）`
  if (typeof before === 'number' && typeof after === 'number') {
    text += ` ${before} → ${after} tokens`
  } else if (messages != null) {
    text += ` · ${messages} 条消息`
  }
  return text
}

/** markdown 渲染结果 memoize（Map 以原文为 key，容量 300，超限逐出最旧项）：避免重渲时重复 parse+sanitize */
const MD_CACHE_MAX = 300
const mdCache = new Map<string, string>()
function cachedMarkdown(text: string): string {
  const hit = mdCache.get(text)
  if (hit !== undefined) return hit
  const html = renderMarkdown(text)
  if (mdCache.size >= MD_CACHE_MAX) {
    // 淘汰最旧插入项（Map 迭代序即插入序）
    const oldest = mdCache.keys().next().value
    if (oldest !== undefined) mdCache.delete(oldest)
  }
  mdCache.set(text, html)
  return html
}

/** 由事件流构建时间线：tool_call/tool_result 按 name+顺序配对（基于渲染窗口内事件） */
function buildTimelineFromEvents(evs: AgentEvent[]): TimelineItem[] {
  const items: TimelineItem[] = []
  /** 每个工具名对应的未匹配 tool_call 下标队列 */
  const pendingCalls = new Map<string, number[]>()

  for (const ev of evs) {
    const p = ev.payload ?? {}
    switch (ev.event_type) {
      case 'llm_response': {
        const text = payloadText(p)
        if (text) items.push({ kind: 'assistant', id: `e${ev.seq}`, text })
        break
      }
      case 'user_message_injected': {
        const text = payloadText(p) || (typeof p.text === 'string' ? p.text : '')
        items.push({ kind: 'user', id: `e${ev.seq}`, text: text ? extractUserText(text) : '(空消息)' })
        break
      }
      case 'compact': {
        // 保留完整 payload JSON 供 compactText 解析真实字段
        items.push({ kind: 'compact', id: `e${ev.seq}`, text: JSON.stringify(p) })
        break
      }
      case 'tool_call': {
        const name = typeof p.tool === 'string' ? p.tool : (typeof p.name === 'string' ? p.name : 'unknown_tool')
        items.push({
          kind: 'tool',
          id: `e${ev.seq}`,
          name,
          input: truncate(p.input ?? p.arguments ?? p.parameters ?? ''),
          output: '',
          durationMs: null,
          isError: false,
        })
        const queue = pendingCalls.get(name) ?? []
        queue.push(items.length - 1)
        pendingCalls.set(name, queue)
        break
      }
      case 'tool_result': {
        const name = typeof p.tool === 'string' ? p.tool : (typeof p.name === 'string' ? p.name : 'unknown_tool')
        const queue = pendingCalls.get(name)
        const idx = queue?.shift()
        const result = {
          output: truncate(p.output ?? p.result ?? ''),
          durationMs: typeof p.duration_ms === 'number' ? p.duration_ms : null,
          isError: p.is_error === true,
        }
        if (idx != null && items[idx] && items[idx].kind === 'tool') {
          Object.assign(items[idx] as ToolTimelineItem, result)
        } else {
          // 没有配对 tool_call 的结果，单独展示
          items.push({
            kind: 'tool',
            id: `e${ev.seq}`,
            name,
            input: '',
            output: result.output,
            durationMs: result.durationMs,
            isError: result.isError,
          })
        }
        break
      }
      default:
        break
    }
  }
  return items
}

/**
 * 各 agent 时间线 computed 缓存（agentKey → items）：
 * 一次遍历 visibleEvents 分组后逐 agent 构建，替代模板中每渲染逐 agent filter 的方法调用。
 */
const timelines = computed(() => {
  const byAgent = new Map<string, AgentEvent[]>()
  for (const ev of store.visibleEvents) {
    const list = byAgent.get(ev.agent_key)
    if (list) list.push(ev)
    else byAgent.set(ev.agent_key, [ev])
  }
  const map = new Map<string, TimelineItem[]>()
  for (const [key, evs] of byAgent) map.set(key, buildTimelineFromEvents(evs))
  return map
})

// ── 滚动控制 ──
const streamEl = ref<HTMLElement | null>(null)
const atBottom = ref(true)

function onScroll() {
  const el = streamEl.value
  if (!el) return
  atBottom.value = el.scrollTop + el.clientHeight >= el.scrollHeight - 60
}

function scrollToBottom(force = false) {
  const el = streamEl.value
  if (!el) return
  if (force) atBottom.value = true
  el.scrollTop = el.scrollHeight
}

/** 流式文本总长度（变化驱动自动滚底） */
const streamingTotalLength = computed(() =>
  Object.values(store.streamingText).reduce((n, s) => n + s.length, 0),
)

/** rAF 节流滚底：text_delta 高频触发时每帧至多滚一次 */
let scrollScheduled = false
function scheduleScrollToBottom() {
  if (!atBottom.value || scrollScheduled) return
  scrollScheduled = true
  requestAnimationFrame(() => {
    scrollScheduled = false
    if (atBottom.value) scrollToBottom()
  })
}

watch(
  [() => store.visibleEvents.length, streamingTotalLength],
  scheduleScrollToBottom,
)

// ── 加载更早 ──
const loadingEarlier = ref(false)

async function onLoadEarlier() {
  loadingEarlier.value = true
  try {
    const el = streamEl.value
    const prevHeight = el?.scrollHeight ?? 0
    await store.loadEarlier()
    // 保持视口停留在原位置（在顶部插入历史后补偿滚动）
    await nextTick()
    if (el) el.scrollTop = el.scrollHeight - prevHeight
  } finally {
    loadingEarlier.value = false
  }
}

// ── 输入与发送 ──
const inputText = ref('')
const sending = ref(false)
const selectedAgent = ref('')

/** 当前运行中的 agents（消息目标候选） */
const runningAgents = computed(() =>
  store.agents.filter(a => a.status === 'running'),
)

// 目标 agent 自动跟随：当前选择失效时切到第一个 running
watch(
  runningAgents,
  (list) => {
    if (list.length === 0) {
      selectedAgent.value = ''
      return
    }
    if (!list.some(a => a.key === selectedAgent.value)) {
      selectedAgent.value = list[list.length - 1].key
    }
  },
  { immediate: true },
)

const canSend = computed(() =>
  isLive.value && store.connected && !!selectedAgent.value && runningAgents.value.length > 0,
)

const inputPlaceholder = computed(() => {
  const target = runningAgents.value.find(a => a.key === selectedAgent.value)
  return target ? `向 ${target.label} 注入消息...` : '暂无运行中的智能体'
})

async function sendMessage() {
  if (sending.value) return // 发送中守卫：防止回车+点击重复发送
  const agentKey = selectedAgent.value
  const text = inputText.value.trim()
  if (!agentKey || !text) return
  sending.value = true
  try {
    const receipt = await store.sendAgentMessage(agentKey, text)
    if (receipt.ok) {
      inputText.value = ''
      ElMessage.success(`消息已注入 ${agentKey}`)
    } else {
      ElMessage.warning(receipt.reason || '消息发送失败')
    }
  } finally {
    sending.value = false
  }
}

// ── 生命周期 ──
async function init() {
  if (props.replay && props.taskId) {
    await store.loadReplay(props.taskId)
  } else if (props.taskId && !store.taskId) {
    store.start(props.taskId)
  }
  await nextTick()
  scrollToBottom(true)
}

void init()

onBeforeUnmount(() => {
  // live 模式下随面板卸载断开（父组件通常在任务完成时才 stop，这里兜底）
  if (!props.replay && store.mode === 'live') store.stop()
})
</script>

<style scoped>
.process-panel {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
  position: relative;
}

.process-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 4px 2px 8px;
  border-bottom: 1px solid var(--el-border-color-lighter);
}

.process-header-left {
  display: flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
}

.status-icon.status-live { color: var(--el-color-success); }
.status-icon.status-connecting { color: var(--el-color-warning); animation: rotating 1.5s linear infinite; }
.status-icon.status-replay { color: var(--el-color-info); }

.process-status-text {
  font-size: 13px;
  font-weight: 600;
  color: var(--el-text-color-primary);
}

.process-header-meta {
  display: flex;
  gap: 8px;
  flex-shrink: 0;
}

.meta-item {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

.process-error { margin-top: 8px; }

.process-empty {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 200px;
}

/* 加载更早按钮 */
.load-earlier {
  flex-shrink: 0;
  display: flex;
  justify-content: center;
  padding: 4px 0;
  border-bottom: 1px dashed var(--el-border-color-lighter);
}

/* 单一纵向滚动容器 */
.stream {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 8px 4px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

/* agent 段落 */
.agent-section {
  border-left: 2px solid var(--el-border-color-lighter);
  padding-left: 10px;
}

.agent-section.is-running {
  border-left-color: var(--el-color-success);
}

.agent-section-head {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 4px 0;
  cursor: pointer;
  user-select: none;
  min-width: 0;
}

.agent-section-head:hover .agent-name { color: var(--el-color-primary); }

.agent-dot {
  font-size: 10px;
  line-height: 1;
  flex-shrink: 0;
}

.agent-dot.is-running {
  color: var(--el-color-success);
  animation: pulse 1.2s ease-in-out infinite;
}

.agent-dot.is-done { color: var(--el-color-success); }

.agent-name {
  font-size: 13px;
  font-weight: 600;
  color: var(--el-text-color-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.agent-state {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  font-size: 12px;
  flex-shrink: 0;
  color: var(--el-text-color-secondary);
}

.agent-state.is-running { color: var(--el-color-success); }
.agent-state.is-done { color: var(--el-color-success); }

.agent-state .is-spinning { animation: rotating 1.5s linear infinite; }

.section-caret {
  margin-left: auto;
  flex-shrink: 0;
  font-size: 12px;
  color: var(--el-text-color-secondary);
  transition: transform 0.15s;
}

.section-caret.expanded { transform: rotate(90deg); }

/* 段内时间线 */
.timeline {
  padding: 6px 0 6px 8px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.timeline-item { display: flex; }

.bubble {
  border-radius: 8px;
  padding: 6px 10px;
  font-size: 13px;
  line-height: 1.6;
  max-width: 100%;
  word-break: break-word;
  white-space: pre-wrap;
}

.assistant-bubble {
  background: var(--el-fill-color-light);
  color: var(--el-text-color-primary);
}

/* markdown 气泡：关闭 pre-wrap，交给 md 结构控制换行 */
.md-bubble {
  white-space: normal;
}

.md-bubble :deep(p) { margin: 0 0 6px; }
.md-bubble :deep(p:last-child) { margin-bottom: 0; }
.md-bubble :deep(ul), .md-bubble :deep(ol) { margin: 4px 0; padding-left: 18px; }
.md-bubble :deep(pre) {
  margin: 4px 0;
  padding: 6px 8px;
  background: var(--el-fill-color-darker);
  border-radius: 4px;
  overflow-x: auto;
  white-space: pre;
}
.md-bubble :deep(code) { font-family: monospace; font-size: 12px; }
.md-bubble :deep(table) { border-collapse: collapse; }
.md-bubble :deep(th), .md-bubble :deep(td) {
  border: 1px solid var(--el-border-color-lighter);
  padding: 2px 6px;
}
.md-bubble :deep(h1), .md-bubble :deep(h2), .md-bubble :deep(h3),
.md-bubble :deep(h4), .md-bubble :deep(h5), .md-bubble :deep(h6) {
  margin: 6px 0 4px;
  font-size: 14px;
}
.md-bubble :deep(blockquote) {
  margin: 4px 0;
  padding-left: 8px;
  border-left: 3px solid var(--el-border-color);
  color: var(--el-text-color-secondary);
}

/* 实时流式气泡样式已随 StreamingBubble.vue 组件化迁入子组件 */

.user-bubble {
  background: var(--el-color-primary-light-9);
  border: 1px solid var(--el-color-primary-light-7);
  display: flex;
  flex-direction: column;
  gap: 2px;
  width: 100%;
}

.user-badge {
  font-size: 11px;
  color: var(--el-color-primary);
  font-weight: 600;
}

.user-text { color: var(--el-text-color-primary); }

/* 工具折叠项 */
.tool-item {
  width: 100%;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 6px;
  background: var(--el-fill-color-blank);
  overflow: hidden;
}

.tool-item.is-error { border-color: var(--el-color-danger-light-5); }

.tool-head {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 5px 10px;
  cursor: pointer;
  user-select: none;
  min-width: 0;
}

.tool-head:hover { background: var(--el-fill-color-light); }

.tool-expand-icon {
  transition: transform 0.15s;
  color: var(--el-text-color-secondary);
  font-size: 12px;
  flex-shrink: 0;
}

.tool-expand-icon.expanded { transform: rotate(90deg); }

.tool-name {
  font-size: 12px;
  font-weight: 600;
  font-family: monospace;
  color: var(--el-text-color-regular);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.tool-duration {
  font-size: 11px;
  color: var(--el-text-color-secondary);
  flex-shrink: 0;
}

.tool-detail {
  border-top: 1px dashed var(--el-border-color-lighter);
  padding: 6px 10px;
}

.tool-block + .tool-block { margin-top: 6px; }

.tool-block-label {
  font-size: 11px;
  color: var(--el-text-color-secondary);
  margin-bottom: 2px;
}

.tool-pre {
  margin: 0;
  font-size: 12px;
  font-family: monospace;
  white-space: pre-wrap;
  word-break: break-all;
  color: var(--el-text-color-regular);
  max-height: 180px;
  overflow-y: auto;
}

.is-error-text { color: var(--el-color-danger); }

/* 压缩提示 */
.compact-bar {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 3px 10px;
  border-radius: 4px;
  background: var(--el-color-warning-light-9);
  color: var(--el-color-warning-dark-2);
  font-size: 12px;
}

/* 回到底部悬浮按钮 */
.scroll-bottom-btn {
  position: absolute;
  right: 16px;
  bottom: 90px;
  z-index: 5;
  padding: 4px 12px;
  font-size: 12px;
  border: 1px solid var(--el-border-color);
  border-radius: 14px;
  background: var(--el-bg-color-overlay);
  color: var(--el-text-color-regular);
  box-shadow: var(--el-box-shadow-light);
  cursor: pointer;
}

.scroll-bottom-btn:hover {
  color: var(--el-color-primary);
  border-color: var(--el-color-primary);
}

.fade-enter-active, .fade-leave-active { transition: opacity 0.2s; }
.fade-enter-from, .fade-leave-to { opacity: 0; }

/* 底部输入区 */
.agent-input-area {
  border-top: 1px solid var(--el-border-color-lighter);
  padding-top: 8px;
  flex-shrink: 0;
}

.input-row {
  display: flex;
  gap: 8px;
  align-items: center;
}

.agent-select {
  width: 160px;
  flex-shrink: 0;
}

.agent-input-disabled {
  font-size: 12px;
  color: var(--el-text-color-placeholder);
  text-align: center;
  padding: 6px 0;
}

@keyframes rotating {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}

@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.35; }
}

/* 窄屏适配（<1200px 时右侧栏更窄） */
@media (max-width: 1200px) {
  .agent-select { width: 120px; }
  .timeline { padding: 4px 2px; }
  .bubble { font-size: 12px; }
  .agent-name { max-width: 140px; }
}
</style>
