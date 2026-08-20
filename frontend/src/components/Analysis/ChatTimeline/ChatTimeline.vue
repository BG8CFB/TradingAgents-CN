<template>
  <div class="chat-timeline">
    <!-- 加载更早事件（该 agent 窗口外还有历史） -->
    <div v-if="hasEarlier" class="load-earlier">
      <el-button size="small" text :loading="loadingEarlier" @click="onLoadEarlier">
        加载更早事件
      </el-button>
    </div>

    <div ref="streamEl" class="chat-stream" @scroll="onScroll">
      <template v-for="msg in messages" :key="msg.id">
        <PromptMessage v-if="msg.kind === 'prompt'" :msg="msg" />
        <ThinkingMessage v-else-if="msg.kind === 'thinking'" :msg="msg" />
        <AssistantMessage v-else-if="msg.kind === 'assistant'" :msg="msg" />
        <UserMessage v-else-if="msg.kind === 'user'" :msg="msg" />
        <SystemBoundary v-else-if="msg.kind === 'boundary'" :msg="msg" />

        <!-- 连续同名工具折叠组 -->
        <div v-else-if="msg.kind === 'tool_group'" class="tool-group">
          <div class="tool-group-head" @click="toggleGroup(msg.id)">
            <el-icon class="caret" :class="{ expanded: expandedGroups[msg.id] }"><ArrowRight /></el-icon>
            <span class="tool-group-name">{{ msg.name }}</span>
            <span class="tool-group-count">× {{ msg.items.length }}</span>
          </div>
          <div v-show="expandedGroups[msg.id]" class="tool-group-body">
            <ToolMessage v-for="t in msg.items" :key="t.id" :msg="t" />
          </div>
        </div>

        <ToolMessage v-else-if="msg.kind === 'tool'" :msg="msg" />
      </template>

      <!-- 运行中：思考流式气泡（先于正文，对齐生成顺序）与 text_delta 实时气泡（独立小组件，delta 只重渲该组件） -->
      <StreamingThinkingBubble v-if="isRunning" :agent-key="agentKey" />
      <StreamingBubble v-if="isRunning" :agent-key="agentKey" />

      <!-- 空态：该 agent 仅有生命周期事件（或旧事件无过程细节）时给出占位，避免空白窗口 -->
      <div v-if="!messages.length && !isRunning" class="chat-empty">
        {{ store.mode === 'replay' ? '该智能体无已录制的过程细节（早于过程录制增强或仅有生命周期事件）' : '暂无过程内容' }}
      </div>
    </div>

    <!-- 回到底部悬浮按钮 -->
    <transition name="fade">
      <button v-if="!atBottom" class="scroll-bottom-btn" type="button" @click="scrollToBottom(true)">
        ↓ 回到底部
      </button>
    </transition>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, reactive, ref, watch } from 'vue'
import { ArrowRight } from '@element-plus/icons-vue'
import { useAnalysisProcessStore } from '@/stores/analysisProcess'
import StreamingBubble from '../StreamingBubble.vue'
import StreamingThinkingBubble from './StreamingThinkingBubble.vue'
import PromptMessage from './PromptMessage.vue'
import ThinkingMessage from './ThinkingMessage.vue'
import AssistantMessage from './AssistantMessage.vue'
import ToolMessage from './ToolMessage.vue'
import UserMessage from './UserMessage.vue'
import SystemBoundary from './SystemBoundary.vue'

const props = defineProps<{
  /** 目标 agent：消息序列与流式气泡均按此 key 从 store 读取 */
  agentKey: string
}>()

const store = useAnalysisProcessStore()

const messages = computed(() => store.chatTimelines.get(props.agentKey) ?? [])
const isRunning = computed(() => (store.agentStatus[props.agentKey] ?? 'running') === 'running')
const hasEarlier = computed(() => store.hasMoreEarlierFor(props.agentKey))

// ── 工具组展开状态（按组 id 持久，避免消息流重建时丢失） ──
const expandedGroups = reactive<Record<string, boolean>>({})
function toggleGroup(id: string) {
  expandedGroups[id] = !expandedGroups[id]
}

// ── 滚动控制（per-agent 独立容器，切 tab 互不影响） ──
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

/** 该 agent 的流式文本/思考长度（变化驱动自动滚底；只依赖本 agent，其他 agent delta 不触发） */
const streamingLength = computed(
  () => (store.streamingText[props.agentKey] ?? '').length
    + (store.streamingThinking[props.agentKey] ?? '').length,
)

watch(
  () => messages.value.length,
  scheduleScrollToBottom,
)
watch(streamingLength, scheduleScrollToBottom)

onMounted(() => scrollToBottom(true))

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
</script>

<style scoped>
.chat-timeline {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  position: relative;
}

.load-earlier {
  flex-shrink: 0;
  display: flex;
  justify-content: center;
  padding: 4px 0;
  border-bottom: 1px dashed var(--el-border-color-lighter);
}

.chat-stream {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 8px 4px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.chat-empty {
  padding: 24px 8px;
  text-align: center;
  font-size: 13px;
  color: var(--el-text-color-secondary);
}

/* 连续同名工具折叠组 */
.tool-group {
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 6px;
  background: var(--el-fill-color-blank);
  overflow: hidden;
}

.tool-group-head {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 5px 10px;
  cursor: pointer;
  user-select: none;
  font-size: 12px;
}

.tool-group-head:hover { background: var(--el-fill-color-light); }

.tool-group-head .caret {
  font-size: 12px;
  color: var(--el-text-color-secondary);
  transition: transform 0.15s;
}

.tool-group-head .caret.expanded { transform: rotate(90deg); }

.tool-group-name {
  font-family: monospace;
  font-weight: 600;
  color: var(--el-text-color-regular);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.tool-group-count {
  color: var(--el-text-color-secondary);
  flex-shrink: 0;
}

.tool-group-body {
  border-top: 1px dashed var(--el-border-color-lighter);
  padding: 6px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

/* 回到底部悬浮按钮 */
.scroll-bottom-btn {
  position: absolute;
  right: 16px;
  bottom: 12px;
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

@media (max-width: 1200px) {
  .chat-stream { padding: 4px 2px; }
}
</style>
