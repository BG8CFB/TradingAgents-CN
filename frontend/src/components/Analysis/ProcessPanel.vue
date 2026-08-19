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

    <!-- 主体：agent 标签页 -->
    <div v-if="store.agents.length === 0" class="process-empty">
      <el-empty :description="isEmptyText" :image-size="60" />
    </div>

    <el-tabs v-else v-model="activeTab" class="process-tabs">
      <el-tab-pane
        v-for="agent in store.agents"
        :key="agent.key"
        :name="agent.key"
      >
        <template #label>
          <span class="agent-tab-label" :title="agent.label">
            <el-icon v-if="agent.status === 'running'" class="agent-status-icon is-running"><Loading /></el-icon>
            <el-icon v-else class="agent-status-icon is-completed"><CircleCheckFilled /></el-icon>
            <span class="agent-name">{{ agent.label }}</span>
          </span>
        </template>

        <div class="agent-body">
          <!-- 消息时间线 -->
          <div :ref="el => setTimelineRef(agent.key, el)" class="timeline">
            <template v-for="item in buildTimeline(agent.key)" :key="item.id">
              <!-- assistant 文本 -->
              <div v-if="item.kind === 'assistant'" class="timeline-item assistant">
                <div class="bubble assistant-bubble">{{ item.text }}</div>
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
                  <div class="tool-head" @click="item.expanded = !item.expanded">
                    <el-icon class="tool-expand-icon" :class="{ expanded: item.expanded }"><ArrowRight /></el-icon>
                    <span class="tool-name">{{ item.name }}</span>
                    <span v-if="item.durationMs != null" class="tool-duration">{{ item.durationMs }}ms</span>
                    <el-tag v-if="item.isError" type="danger" size="small" effect="plain">错误</el-tag>
                  </div>
                  <div v-show="item.expanded" class="tool-detail">
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
                  <span>上下文已压缩 {{ item.text ? `— ${item.text}` : '' }}</span>
                </div>
              </div>
            </template>
          </div>

          <!-- 底部输入区：仅 running agent 可发消息 -->
          <div v-if="isLive" class="agent-input-area">
            <template v-if="agent.status === 'running'">
              <el-input
                v-model="inputTexts[agent.key]"
                size="small"
                :placeholder="`向 ${agent.label} 注入消息...`"
                :disabled="sendingMap[agent.key]"
                @keyup.enter="sendMessage(agent.key)"
              />
              <el-button
                size="small"
                type="primary"
                :loading="sendingMap[agent.key]"
                :disabled="!store.connected"
                @click="sendMessage(agent.key)"
              >
                发送
              </el-button>
            </template>
            <div v-else class="agent-input-disabled">
              该智能体已完成，仅分析中的智能体可接收消息
            </div>
          </div>
        </div>
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, computed, watch, onBeforeUnmount, nextTick } from 'vue'
import { ElMessage } from 'element-plus'
import { Connection, Loading, VideoPlay, CircleCheckFilled, ArrowRight, WarningFilled } from '@element-plus/icons-vue'
import { useAnalysisProcessStore } from '@/stores/analysisProcess'

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

// ── tab 状态 ──
const activeTab = ref('')

// agent 首次出现时自动选中第一个
watch(
  () => store.agentOrder.length,
  async () => {
    if (!activeTab.value && store.agentOrder.length > 0) {
      activeTab.value = store.agentOrder[0]
      await nextTick()
      scrollToBottom(store.agentOrder[0])
    }
  },
)

// 新事件到达时，若当前 tab 无输入焦点则自动滚动到底部
watch(
  () => store.events.length,
  async () => {
    const key = activeTab.value
    if (!key) return
    await nextTick()
    if (!inputTexts[key]) scrollToBottom(key)
  },
)

// ── 时间线视图模型 ──
interface ToolTimelineItem {
  kind: 'tool'
  id: string
  name: string
  input: string
  output: string
  durationMs: number | null
  isError: boolean
  expanded: boolean
}
interface TextTimelineItem {
  kind: 'assistant' | 'user' | 'compact'
  id: string
  text: string
}
type TimelineItem = ToolTimelineItem | TextTimelineItem

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

/** 由事件流构建时间线：tool_call/tool_result 按 name+顺序配对 */
function buildTimeline(agentKey: string): TimelineItem[] {
  const evs = store.events.filter(e => e.agent_key === agentKey)
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
        items.push({ kind: 'compact', id: `e${ev.seq}`, text: payloadText(p) })
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
          expanded: false,
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
            expanded: false,
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

// ── 输入与发送 ──
const inputTexts = reactive<Record<string, string>>({})
const sendingMap = reactive<Record<string, boolean>>({})

async function sendMessage(agentKey: string) {
  const text = (inputTexts[agentKey] ?? '').trim()
  if (!text) return
  sendingMap[agentKey] = true
  try {
    const receipt = await store.sendAgentMessage(agentKey, text)
    if (receipt.ok) {
      inputTexts[agentKey] = ''
      ElMessage.success(`消息已注入 ${agentKey}`)
    } else {
      ElMessage.warning(receipt.reason || '消息发送失败')
    }
  } finally {
    sendingMap[agentKey] = false
  }
}

// ── 自动滚动 ──
const timelineRefs = new Map<string, unknown>()

function setTimelineRef(key: string, el: unknown) {
  if (el) timelineRefs.set(key, el)
}

function scrollToBottom(key: string) {
  const el = timelineRefs.get(key)
  if (el instanceof HTMLElement) el.scrollTop = el.scrollHeight
}

// ── 生命周期 ──
async function init() {
  if (props.replay && props.taskId) {
    await store.loadReplay(props.taskId)
    if (store.agentOrder.length > 0) {
      activeTab.value = store.agentOrder[0]
      await nextTick()
      scrollToBottom(store.agentOrder[0])
    }
  } else if (props.taskId && !store.taskId) {
    store.start(props.taskId)
  }
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

.process-tabs {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
}

.process-tabs :deep(.el-tabs__content) {
  flex: 1;
  min-height: 0;
  overflow: hidden;
}

.process-tabs :deep(.el-tabs__nav-wrap.is-scrollable) {
  /* 窄屏时允许标签横向滚动，避免换行挤压 */
  overflow-x: auto;
}

.agent-tab-label {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  max-width: 140px;
}

.agent-name {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.agent-status-icon.is-running { color: var(--el-color-success); animation: rotating 1.5s linear infinite; }
.agent-status-icon.is-completed { color: var(--el-color-success); }

.agent-body {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 220px;
}

.timeline {
  flex: 1;
  overflow-y: auto;
  padding: 8px 4px;
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
}

.tool-head:hover { background: var(--el-fill-color-light); }

.tool-expand-icon {
  transition: transform 0.15s;
  color: var(--el-text-color-secondary);
  font-size: 12px;
}

.tool-expand-icon.expanded { transform: rotate(90deg); }

.tool-name {
  font-size: 12px;
  font-weight: 600;
  font-family: monospace;
  color: var(--el-text-color-regular);
}

.tool-duration {
  font-size: 11px;
  color: var(--el-text-color-secondary);
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

/* 底部输入区 */
.agent-input-area {
  border-top: 1px solid var(--el-border-color-lighter);
  padding-top: 8px;
  flex-shrink: 0;
}

.agent-input-area :deep(.el-input) {
  margin-bottom: 6px;
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

/* 窄屏适配（<1200px 时右侧栏更窄） */
@media (max-width: 1200px) {
  .agent-tab-label { max-width: 90px; }
  .timeline { padding: 6px 2px; }
  .bubble { font-size: 12px; }
}
</style>
