<template>
  <div class="chat-item user-item">
    <div class="user-bubble" :class="{ 'is-local': msg.local }">
      <span class="user-badge">{{ msg.local ? '用户消息（发送中）' : '用户注入' }}</span>
      <span class="user-text">{{ msg.text }}</span>
    </div>
  </div>
</template>

<script setup lang="ts">
import type { UserChatMessage } from './buildChatMessages'

defineProps<{ msg: UserChatMessage }>()
</script>

<style scoped>
.user-item { display: flex; }

.user-bubble {
  background: var(--el-color-primary-light-9);
  border: 1px solid var(--el-color-primary-light-7);
  border-radius: 8px;
  padding: 6px 10px;
  font-size: 13px;
  line-height: 1.6;
  display: flex;
  flex-direction: column;
  gap: 2px;
  max-width: 100%;
  word-break: break-word;
  white-space: pre-wrap;
}

.user-bubble.is-local { opacity: 0.75; }

.user-badge {
  font-size: 11px;
  color: var(--el-color-primary);
  font-weight: 600;
}

.user-text { color: var(--el-text-color-primary); }

@media (max-width: 1200px) {
  .user-bubble { font-size: 12px; }
}
</style>
