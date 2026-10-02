<template>
  <div class="input-box">
    <div v-if="hintText" class="input-hint">
      <el-icon><InfoFilled /></el-icon>
      <span>{{ hintText }}</span>
    </div>

    <div class="input-row">
      <el-input
        v-model="draft"
        type="textarea"
        :rows="2"
        :maxlength="4000"
        show-word-limit
        resize="none"
        :placeholder="placeholder"
        :disabled="disabled"
        @keydown.enter.exact.prevent="trySend"
      />
      <div class="input-actions">
        <el-button
          v-if="running"
          type="danger"
          plain
          :icon="VideoPause"
          @click="emit('stop')"
        >
          停止
        </el-button>
        <el-button
          v-else
          type="primary"
          :icon="Promotion"
          :disabled="!canSend"
          @click="trySend"
        >
          发送
        </el-button>
      </div>
    </div>

    <div class="input-footer">
      <span>Enter 发送 · Shift+Enter 换行</span>
      <span v-if="quotaRemaining !== null && quotaRemaining >= 0">今日剩余 {{ quotaRemaining }} 轮</span>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { InfoFilled, Promotion, VideoPause } from '@element-plus/icons-vue'

const props = defineProps<{
  running: boolean
  wsConnected: boolean
  quotaRemaining: number | null
  /** 功能未启用（503）时锁输入 */
  disabled: boolean
}>()

const emit = defineEmits<{
  send: [content: string]
  stop: []
}>()

const draft = ref('')

const canSend = computed(() => !props.disabled && props.wsConnected && draft.value.trim().length > 0)

const placeholder = computed(() => {
  if (props.disabled) return 'AI 问答助手未启用（系统设置 → AI 问答助手）'
  if (!props.wsConnected) return '正在连接问答通道…'
  return '例如：今天有哪些推荐股票？/ 帮我用短线强势策略筛几只银行股'
})

const hintText = computed(() => {
  if (props.disabled) return 'AI 问答助手未启用，请管理员在「系统设置 → 配置管理 → AI 问答助手」中开启'
  if (!props.wsConnected) return '问答通道连接中，稍候即可发送'
  return ''
})

function trySend() {
  const content = draft.value.trim()
  if (!content) return
  if (!canSend.value) {
    ElMessage.warning(props.wsConnected ? '请输入内容' : '问答通道未连接')
    return
  }
  emit('send', content)
  draft.value = ''
}
</script>

<style scoped>
.input-box {
  border-top: 1px solid var(--el-border-color-lighter);
  padding: 10px 16px 8px;
  background: var(--el-bg-color);
}

.input-hint {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
  margin-bottom: 6px;
}

.input-row {
  display: flex;
  gap: 10px;
  align-items: flex-end;
}

.input-row :deep(.el-textarea) { flex: 1; }

.input-actions { flex-shrink: 0; }

.input-footer {
  display: flex;
  justify-content: space-between;
  font-size: 11px;
  color: var(--el-text-color-placeholder);
  margin-top: 4px;
}
</style>
