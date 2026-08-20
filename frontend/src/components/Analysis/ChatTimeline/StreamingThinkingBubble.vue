<template>
  <div v-if="text" class="chat-item thinking-item">
    <div class="thinking-head" @click="expanded = !expanded">
      <el-icon class="caret" :class="{ expanded }"><ArrowRight /></el-icon>
      <el-icon :size="12"><MagicStick /></el-icon>
      <span class="thinking-title">思考中</span>
      <span class="thinking-meta">{{ text.length }} 字</span>
    </div>
    <pre v-show="expanded" class="thinking-body">{{ text }}<span class="streaming-cursor">▌</span></pre>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { ArrowRight, MagicStick } from '@element-plus/icons-vue'
import { useAnalysisProcessStore } from '@/stores/analysisProcess'

const props = defineProps<{
  /** 目标 agent：本组件直接从 store 读取流式思考，
   * 使 thinking_delta 高频变更只触发本小组件重渲，父组件不建立对 streamingThinking 的渲染依赖 */
  agentKey: string
}>()

const store = useAnalysisProcessStore()

/** 实时流式思考（thinking_delta 累积），无内容时不渲染；流式期间默认展开，聚合事件落 timeline 后本气泡消失 */
const text = computed(() => store.streamingThinking[props.agentKey] ?? '')
const expanded = ref(true)
</script>

<style scoped>
.thinking-item { display: flex; flex-direction: column; gap: 4px; }

.thinking-head {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 3px 8px;
  border-radius: 6px;
  background: var(--el-fill-color-light);
  cursor: pointer;
  user-select: none;
  font-size: 12px;
  color: var(--el-text-color-secondary);
  width: fit-content;
}

.thinking-head:hover { background: var(--el-fill-color); }

.caret { font-size: 12px; transition: transform 0.15s; }
.caret.expanded { transform: rotate(90deg); }

.thinking-title { font-style: italic; color: var(--el-text-color-secondary); }

.thinking-meta { font-size: 11px; color: var(--el-text-color-placeholder); }

.thinking-body {
  margin: 0;
  font-size: 12px;
  font-family: inherit;
  white-space: pre-wrap;
  word-break: break-word;
  color: var(--el-text-color-secondary);
  border-left: 2px solid var(--el-border-color-lighter);
  padding: 2px 8px;
  max-height: 300px;
  overflow-y: auto;
}

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
</style>
