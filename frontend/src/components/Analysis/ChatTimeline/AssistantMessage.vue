<template>
  <!-- eslint-disable-next-line vue/no-v-html -- DOMPurify 消毒后的 markdown HTML（memoize 缓存） -->
  <div v-if="!msg.missing" class="chat-item assistant-item bubble md-bubble chat-md" v-html="cachedMarkdown(msg.text)"></div>
  <!-- 旧事件降级：未保存助手原文 -->
  <div v-else class="chat-item assistant-item assistant-placeholder">
    <el-icon :size="12"><InfoFilled /></el-icon>
    <span>该记录早于过程录制增强，未保存助手原文</span>
  </div>
</template>

<script setup lang="ts">
import { InfoFilled } from '@element-plus/icons-vue'
import type { AssistantChatMessage } from './buildChatMessages'
import { cachedMarkdown } from './markdownCache'
import './md-styles.css'

defineProps<{ msg: AssistantChatMessage }>()
</script>

<style scoped>
.assistant-item {
  border-radius: 8px;
  padding: 6px 10px;
  font-size: 13px;
  line-height: 1.6;
  max-width: 100%;
  word-break: break-word;
  background: var(--el-fill-color-light);
  color: var(--el-text-color-primary);
}

.assistant-placeholder {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: var(--el-text-color-placeholder);
  background: var(--el-fill-color-lighter);
}

@media (max-width: 1200px) {
  .assistant-item { font-size: 12px; }
}
</style>
