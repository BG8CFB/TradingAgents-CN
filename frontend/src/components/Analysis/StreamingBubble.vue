<template>
  <div v-if="text" class="timeline-item assistant">
    <div class="bubble assistant-bubble streaming-bubble">{{ text }}<span class="streaming-cursor">▌</span></div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useAnalysisProcessStore } from '@/stores/analysisProcess'

const props = defineProps<{
  /** 目标 agent：本组件直接从 store 读取流式文本，
   * 使 text_delta 高频变更只触发本小组件重渲，父组件不建立对 streamingText 的渲染依赖 */
  agentKey: string
}>()

const store = useAnalysisProcessStore()

/** 实时流式文本（text_delta 累积），无内容时不渲染 */
const text = computed(() => store.streamingText[props.agentKey] ?? '')
</script>

<style scoped>
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

.streaming-bubble { white-space: pre-wrap; }

.streaming-cursor {
  display: inline-block;
  margin-left: 2px;
  color: var(--el-color-success);
  animation: streaming-pulse 1s ease-in-out infinite;
}

@keyframes streaming-pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.35; }
}

@media (max-width: 1200px) {
  .bubble { font-size: 12px; }
}
</style>
