<template>
  <div class="chat-item thinking-item">
    <div class="thinking-head" @click="expanded = !expanded">
      <el-icon class="caret" :class="{ expanded }"><ArrowRight /></el-icon>
      <el-icon :size="12"><MagicStick /></el-icon>
      <span class="thinking-title">思考</span>
      <span class="thinking-meta">{{ msg.text.length }} 字</span>
    </div>
    <pre v-show="expanded" class="thinking-body">{{ msg.text }}</pre>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { ArrowRight, MagicStick } from '@element-plus/icons-vue'
import type { ThinkingChatMessage } from './buildChatMessages'

defineProps<{ msg: ThinkingChatMessage }>()
const expanded = ref(false) // 默认折叠，与 Claude Code 行为一致
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
</style>
