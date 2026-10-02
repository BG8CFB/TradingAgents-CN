<template>
  <div class="chat-item assistant-item bubble md-bubble chat-md streaming-text">
    <span class="stream-body">{{ text }}</span><span v-if="showCursor" class="stream-cursor" />
  </div>
</template>

<script setup lang="ts">
/** 流式正文气泡：text_delta 实时渲染，running 时尾随闪烁光标 */
defineProps<{
  text: string
  showCursor: boolean
}>()
</script>

<style scoped>
.streaming-text {
  border-radius: 8px;
  padding: 6px 10px;
  font-size: 13px;
  line-height: 1.7;
  max-width: 100%;
  word-break: break-word;
  white-space: pre-wrap;
  background: var(--el-fill-color-light);
  color: var(--el-text-color-primary);
}

.stream-body { white-space: pre-wrap; }

.stream-cursor {
  display: inline-block;
  width: 7px;
  height: 14px;
  margin-left: 2px;
  vertical-align: text-bottom;
  background: var(--el-color-primary);
  animation: cursor-blink 1s step-end infinite;
}

@keyframes cursor-blink {
  0%, 100% { opacity: 1; }
  50% { opacity: 0; }
}
</style>
