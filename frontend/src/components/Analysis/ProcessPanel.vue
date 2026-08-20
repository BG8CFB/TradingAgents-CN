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

    <!-- 主体：每个 agent 一个对话窗口 tab -->
    <template v-else>
      <!-- agent tab 条：显示名 + 状态点 + 未读红点 -->
      <div class="agent-tabs">
        <button
          v-for="agent in agents"
          :key="agent.key"
          type="button"
          class="agent-tab"
          :class="{ 'is-active': agent.key === activeAgentKey }"
          @click="selectAgent(agent.key)"
        >
          <span class="agent-dot" :class="agent.status === 'running' ? 'is-running' : 'is-done'">●</span>
          <span class="agent-tab-label" :title="agent.label">{{ agent.label }}</span>
          <span v-if="agent.key !== activeAgentKey && hasUnread(agent.key)" class="unread-dot"></span>
        </button>
      </div>

      <!-- 当前 tab 内容（v-if：未激活 tab 不渲染，保证多 agent 场景渲染量可控） -->
      <ChatTimeline v-if="activeAgentKey" :key="activeAgentKey" :agent-key="activeAgentKey" />

      <!-- 底部输入区：目标 = 当前 tab 的 agent（仅运行中可发） -->
      <div v-if="isLive" class="agent-input-area">
        <div class="input-row">
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
        <div v-if="!canSend" class="agent-input-disabled">{{ inputDisabledText }}</div>
      </div>
    </template>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { Connection, Loading, VideoPlay } from '@element-plus/icons-vue'
import { useAnalysisProcessStore } from '@/stores/analysisProcess'
import ChatTimeline from './ChatTimeline/ChatTimeline.vue'

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

// ── agent tab ──
const agents = computed(() =>
  store.agentOrder.map(key => ({
    key,
    label: store.agentLabels[key] ?? key,
    status: store.agentStatus[key] ?? 'running',
  })),
)

const activeAgentKey = ref('')
/** 用户是否手动切换过 tab：之后不再自动跟随运行中的 agent */
let userSwitched = false

/** 每 agent 最近一次被查看时的最新 seq（未读 = 有更新的事件且 tab 未激活） */
const lastViewedSeq = reactive<Record<string, number>>({})

/** 每 agent 当前最新 seq（来自渲染窗口尾部；乐观消息 seq<0 不计未读） */
const latestSeqByAgent = computed(() => {
  const map: Record<string, number> = {}
  for (const [key, evs] of store.visibleEventsByAgent) {
    let max = -Infinity
    for (const ev of evs) if (ev.seq > max) max = ev.seq
    if (max !== -Infinity) map[key] = max
  }
  return map
})

function hasUnread(agentKey: string): boolean {
  const latest = latestSeqByAgent.value[agentKey]
  if (latest === undefined) return false
  const viewed = lastViewedSeq[agentKey]
  return viewed === undefined ? false : latest > viewed
}

function selectAgent(agentKey: string) {
  if (agentKey !== activeAgentKey.value) userSwitched = true
  activeAgentKey.value = agentKey
  markViewed(agentKey)
}

function markViewed(agentKey: string) {
  const latest = latestSeqByAgent.value[agentKey]
  if (latest !== undefined) lastViewedSeq[agentKey] = latest
}

// 激活 tab 存在性维护：失效时回落到第一个 agent
watch(
  () => agents.value.map(a => a.key),
  (keys) => {
    if (keys.length === 0) {
      activeAgentKey.value = ''
      return
    }
    if (!keys.includes(activeAgentKey.value)) {
      activeAgentKey.value = keys[0]
      markViewed(keys[0])
    }
  },
  { immediate: true },
)

// 运行中 agent 自动激活：用户手动切换过之前，跟随最新进入 running 的 agent
watch(
  () => agents.value.filter(a => a.status === 'running').map(a => a.key),
  (runningKeys) => {
    if (userSwitched || runningKeys.length === 0) return
    const latestRunning = runningKeys[runningKeys.length - 1]
    if (latestRunning && latestRunning !== activeAgentKey.value) {
      activeAgentKey.value = latestRunning
      markViewed(latestRunning)
    }
  },
  { immediate: true },
)

// 激活 tab 有新事件 → 即时标记已读（tab 正在查看中）
watch(
  () => (activeAgentKey.value ? latestSeqByAgent.value[activeAgentKey.value] : undefined),
  () => {
    if (activeAgentKey.value) markViewed(activeAgentKey.value)
  },
)

// ── 底部输入与发送（目标 = 当前 tab agent） ──
const inputText = ref('')
const sending = ref(false)

const activeAgent = computed(() => agents.value.find(a => a.key === activeAgentKey.value) ?? null)

const canSend = computed(() =>
  isLive.value
  && store.connected
  && !!activeAgent.value
  && activeAgent.value.status === 'running',
)

const inputPlaceholder = computed(() => {
  if (!activeAgent.value) return '暂无智能体'
  return activeAgent.value.status === 'running'
    ? `向 ${activeAgent.value.label} 注入消息...`
    : `${activeAgent.value.label} 已完成，无法接收消息`
})

const inputDisabledText = computed(() => {
  if (!store.connected && isLive.value) return '连接未就绪，无法发送消息'
  return '仅运行中的智能体可接收消息，切换到运行中的智能体 tab 后可发送'
})

async function sendMessage() {
  if (sending.value) return // 发送中守卫：防止回车+点击重复发送
  const agentKey = activeAgentKey.value
  const agent = activeAgent.value
  const text = inputText.value.trim()
  if (!agentKey || !text) return
  if (!agent || agent.status !== 'running') {
    ElMessage.warning('该智能体已完成，无法接收消息')
    return
  }
  sending.value = true
  try {
    const receipt = await store.sendAgentMessage(agentKey, text)
    if (receipt.ok) {
      inputText.value = ''
      ElMessage.success(`消息已注入 ${agent.label}`)
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
  flex-shrink: 0;
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

/* ── agent tab 条（横向滚动） ── */
.agent-tabs {
  display: flex;
  gap: 4px;
  padding: 6px 0;
  border-bottom: 1px solid var(--el-border-color-lighter);
  overflow-x: auto;
  flex-shrink: 0;
}

.agent-tabs::-webkit-scrollbar { height: 4px; }
.agent-tabs::-webkit-scrollbar-thumb { background: var(--el-border-color); border-radius: 2px; }

.agent-tab {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 4px 10px;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 14px;
  background: var(--el-fill-color-blank);
  color: var(--el-text-color-regular);
  font-size: 12px;
  cursor: pointer;
  white-space: nowrap;
  flex-shrink: 0;
  position: relative;
}

.agent-tab:hover { color: var(--el-color-primary); }

.agent-tab.is-active {
  color: var(--el-color-primary);
  border-color: var(--el-color-primary-light-5);
  background: var(--el-color-primary-light-9);
  font-weight: 600;
}

.agent-dot {
  font-size: 10px;
  line-height: 1;
  flex-shrink: 0;
}

.agent-dot.is-running {
  color: var(--el-color-success);
  animation: tab-pulse 1.2s ease-in-out infinite;
}

.agent-dot.is-done { color: var(--el-color-success); }

.agent-tab-label {
  max-width: 140px;
  overflow: hidden;
  text-overflow: ellipsis;
}

.unread-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--el-color-danger);
  flex-shrink: 0;
}

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

@keyframes tab-pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.35; }
}

/* 窄屏适配 */
@media (max-width: 1200px) {
  .agent-tab-label { max-width: 100px; }
}
</style>
