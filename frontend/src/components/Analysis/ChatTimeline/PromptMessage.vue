<template>
  <div class="chat-item prompt-item">
    <!-- 首轮：完整消息原文，默认折叠可展开 -->
    <template v-if="msg.messagesFull && msg.messages && msg.messages.length">
      <div class="prompt-head" @click="expanded = !expanded">
        <el-icon class="caret" :class="{ expanded }"><ArrowRight /></el-icon>
        <span class="prompt-title">输入上下文</span>
        <span class="prompt-meta">{{ msg.messages.length }} 条消息</span>
      </div>
      <div v-show="expanded" class="prompt-body">
        <div v-for="(m, i) in msg.messages" :key="i" class="prompt-msg">
          <el-tag size="small" :type="roleTagType(m.role)" effect="plain" class="role-tag">{{ m.role }}</el-tag>
          <pre class="prompt-pre">{{ m.content }}</pre>
        </div>
      </div>
    </template>
    <!-- 后续轮次 / 旧事件：条数摘要行 -->
    <div v-else class="prompt-summary">
      <el-icon :size="12"><Promotion /></el-icon>
      <span>发送请求<span v-if="msg.messagesCount != null"> · {{ msg.messagesCount }} 条消息</span></span>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { ArrowRight, Promotion } from '@element-plus/icons-vue'
import type { PromptChatMessage } from './buildChatMessages'

defineProps<{ msg: PromptChatMessage }>()
const expanded = ref(false)

function roleTagType(role: string): 'primary' | 'success' | 'info' | 'warning' {
  if (role === 'user') return 'primary'
  if (role === 'assistant') return 'success'
  if (role === 'system' || role === 'developer') return 'warning'
  return 'info'
}
</script>

<style scoped>
.prompt-item { display: flex; flex-direction: column; gap: 4px; }

.prompt-head {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 4px 8px;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 6px;
  background: var(--el-fill-color-blank);
  cursor: pointer;
  user-select: none;
  font-size: 12px;
}

.prompt-head:hover { background: var(--el-fill-color-light); }

.caret { font-size: 12px; color: var(--el-text-color-secondary); transition: transform 0.15s; }
.caret.expanded { transform: rotate(90deg); }

.prompt-title { font-weight: 600; color: var(--el-text-color-regular); }

.prompt-meta { color: var(--el-text-color-secondary); font-size: 11px; }

.prompt-body {
  border: 1px dashed var(--el-border-color-lighter);
  border-radius: 6px;
  padding: 6px 8px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.prompt-msg { display: flex; gap: 6px; align-items: flex-start; }

.role-tag { flex-shrink: 0; margin-top: 1px; }

.prompt-pre {
  margin: 0;
  flex: 1;
  min-width: 0;
  font-size: 12px;
  font-family: monospace;
  white-space: pre-wrap;
  word-break: break-word;
  color: var(--el-text-color-regular);
  max-height: 220px;
  overflow-y: auto;
  background: var(--el-fill-color-light);
  border-radius: 4px;
  padding: 4px 6px;
}

/* 摘要行（后续轮次 / 旧事件降级） */
.prompt-summary {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
  padding: 2px 4px;
}
</style>
