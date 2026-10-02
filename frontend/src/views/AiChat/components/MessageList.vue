<template>
  <div ref="listRef" class="message-list">
    <el-empty
      v-if="!messages.length && !running"
      description="问点什么吧，例如「今天有哪些推荐股票？」、「000001 的因子怎么样」"
      :image-size="80"
    />

    <template v-for="msg in messages" :key="msg.id">
      <!-- 用户提问：右对齐气泡（区别于分析过程的「注入」语义） -->
      <div v-if="msg.kind === 'user'" class="chat-item user-row">
        <div class="user-bubble" :class="{ 'is-local': msg.local }">{{ msg.text }}</div>
      </div>

      <AssistantMessage v-else-if="msg.kind === 'assistant'" :msg="msg" />
      <ThinkingMessage v-else-if="msg.kind === 'thinking'" :msg="msg" />
      <ToolMessage v-else-if="msg.kind === 'tool'" :msg="msg" />

      <!-- 轮次失败提示（failed 不扣配额，可直接重试） -->
      <div v-else-if="msg.kind === 'error'" class="chat-item error-item">
        <el-icon><WarningFilled /></el-icon>
        <span>{{ msg.text }}</span>
      </div>
    </template>

    <!-- 轮内实时区：流式思考 → 工具消息（已在 messages 中）→ 流式正文 -->
    <ThinkingMessage
      v-if="streamingThinking"
      :msg="{ kind: 'thinking', id: 'stream:thinking', text: streamingThinking }"
    />
    <StreamingText v-if="streamingText" :text="streamingText" :show-cursor="running" />
    <div v-if="running && !streamingText && !streamingThinking" class="chat-item waiting-item">
      <el-icon class="is-loading"><Loading /></el-icon>
      <span>思考中…</span>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, watch, nextTick } from 'vue'
import { Loading, WarningFilled } from '@element-plus/icons-vue'
import AssistantMessage from '@/components/Analysis/ChatTimeline/AssistantMessage.vue'
import ThinkingMessage from '@/components/Analysis/ChatTimeline/ThinkingMessage.vue'
import ToolMessage from '@/components/Analysis/ChatTimeline/ToolMessage.vue'
import StreamingText from './StreamingText.vue'
import type { UIMessage } from '@/stores/chatProcess'

const props = defineProps<{
  messages: UIMessage[]
  streamingText: string
  streamingThinking: string
  running: boolean
}>()

const listRef = ref<HTMLElement | null>(null)

/** 新消息/流式增量到达时自动滚到底（用户手动上滚时不打扰的逻辑从简：始终跟随） */
watch(
  () => [props.messages.length, props.streamingText, props.streamingThinking],
  async () => {
    await nextTick()
    const el = listRef.value
    if (el) el.scrollTop = el.scrollHeight
  }
)
</script>

<style scoped>
.message-list {
  flex: 1;
  overflow-y: auto;
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.chat-item { display: flex; }

.user-row { justify-content: flex-end; }

.user-bubble {
  background: var(--el-color-primary-light-9);
  border: 1px solid var(--el-color-primary-light-7);
  border-radius: 10px;
  padding: 8px 12px;
  font-size: 13px;
  line-height: 1.6;
  max-width: 80%;
  word-break: break-word;
  white-space: pre-wrap;
}

.user-bubble.is-local { opacity: 0.75; }

.error-item {
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: var(--el-color-danger);
  background: var(--el-color-danger-light-9);
  border: 1px solid var(--el-color-danger-light-7);
  border-radius: 8px;
  padding: 6px 10px;
}

.waiting-item {
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
</style>
