<template>
  <div class="chat-item tool-item" :class="{ 'is-error': msg.isError }">
    <div class="tool-head" @click="expanded = !expanded">
      <el-icon class="tool-expand-icon" :class="{ expanded }"><ArrowRight /></el-icon>
      <span class="tool-name">{{ msg.name }}</span>
      <span v-if="!msg.hasResult" class="tool-pending">
        <el-icon class="is-spinning"><Loading /></el-icon>
      </span>
      <span v-else-if="msg.durationMs != null" class="tool-duration">{{ msg.durationMs }}ms</span>
      <el-tag v-if="msg.isError" type="danger" size="small" effect="plain">错误</el-tag>
    </div>
    <div v-show="expanded" class="tool-detail">
      <div v-if="msg.input" class="tool-block">
        <div class="tool-block-label">参数</div>
        <pre class="tool-pre">{{ msg.input }}</pre>
      </div>
      <div v-if="msg.output" class="tool-block">
        <div class="tool-block-label">结果</div>
        <pre class="tool-pre" :class="{ 'is-error-text': msg.isError }">{{ msg.output }}</pre>
      </div>
      <div v-if="!msg.input && !msg.output && msg.hasResult" class="tool-block tool-empty">
        （无输出）
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { ArrowRight, Loading } from '@element-plus/icons-vue'
import type { ToolChatMessage } from './buildChatMessages'

defineProps<{ msg: ToolChatMessage }>()
const expanded = ref(false)
</script>

<style scoped>
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

.tool-pending { display: inline-flex; color: var(--el-color-success); }
.tool-pending .is-spinning { animation: tool-rotating 1.5s linear infinite; }

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

.tool-empty { font-size: 12px; color: var(--el-text-color-placeholder); }

.is-error-text { color: var(--el-color-danger); }

@keyframes tool-rotating {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}
</style>
