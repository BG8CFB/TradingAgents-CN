<template>
  <div class="chat-item boundary-item">
    <div class="boundary-bar">
      <el-icon :size="12"><WarningFilled /></el-icon>
      <span>{{ msg.text }}</span>
    </div>
  </div>
</template>

<script setup lang="ts">
import { WarningFilled } from '@element-plus/icons-vue'
import type { BoundaryChatMessage } from './buildChatMessages'

defineProps<{ msg: BoundaryChatMessage }>()
</script>

<style scoped>
.boundary-item { display: flex; }

.boundary-bar {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 3px 10px;
  border-radius: 4px;
  background: var(--el-color-warning-light-9);
  color: var(--el-color-warning-dark-2);
  font-size: 12px;
}
</style>
