<template>
  <div class="session-sidebar">
    <div class="sidebar-header">
      <span class="sidebar-title">会话</span>
      <el-button type="primary" size="small" :icon="Plus" @click="emit('create')" :loading="creating">
        新会话
      </el-button>
    </div>

    <el-scrollbar class="session-list">
      <div
        v-for="s in sessions"
        :key="s.session_id"
        class="session-item"
        :class="{ active: s.session_id === currentSessionId }"
        @click="emit('select', s.session_id)"
      >
        <div class="session-main">
          <div class="session-title">{{ s.title || '新会话' }}</div>
          <div class="session-meta">{{ formatTime(s.updated_at) }} · {{ s.message_count }} 条</div>
        </div>
        <el-icon class="session-delete" @click.stop="confirmRemove(s)"><Delete /></el-icon>
      </div>
      <el-empty v-if="!sessions.length" description="暂无会话" :image-size="60" />
    </el-scrollbar>
  </div>
</template>

<script setup lang="ts">
import { ElMessageBox, ElMessage } from 'element-plus'
import { Delete, Plus } from '@element-plus/icons-vue'
import type { ChatSession } from '@/api/chat'

defineProps<{
  sessions: ChatSession[]
  currentSessionId: string
  creating: boolean
}>()

const emit = defineEmits<{
  create: []
  select: [sessionId: string]
  remove: [sessionId: string]
}>()

function formatTime(iso: string): string {
  // ISO 本地时间字符串 → "MM-DD HH:mm"；非本地格式原样截断展示
  const m = iso.match(/T(\d{2}-\d{2})[T ](\d{2}:\d{2})/)
  return m ? `${m[1]} ${m[2]}` : iso.slice(5, 16)
}

function confirmRemove(s: ChatSession) {
  ElMessageBox.confirm(
    s.title ? `删除会话「${s.title}」？消息记录将保留但不再展示。` : '删除该会话？',
    '删除会话',
    { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' }
  )
    .then(() => {
      emit('remove', s.session_id)
    })
    .catch(() => {
      /* 取消删除 */
      ElMessage.info('已取消')
    })
}
</script>

<style scoped>
.session-sidebar {
  display: flex;
  flex-direction: column;
  height: 100%;
  border-right: 1px solid var(--el-border-color-lighter);
  background: var(--el-bg-color);
}

.sidebar-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px;
  border-bottom: 1px solid var(--el-border-color-lighter);
}

.sidebar-title { font-weight: 600; font-size: 14px; }

.session-list { flex: 1; }

.session-item {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 10px 12px;
  cursor: pointer;
  border-bottom: 1px solid var(--el-border-color-extra-light);
  transition: background 0.15s;
}

.session-item:hover { background: var(--el-fill-color-light); }

.session-item.active {
  background: var(--el-color-primary-light-9);
}

.session-item.active .session-title { color: var(--el-color-primary); font-weight: 600; }

.session-main { flex: 1; min-width: 0; }

.session-title {
  font-size: 13px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.session-meta {
  font-size: 11px;
  color: var(--el-text-color-secondary);
  margin-top: 2px;
}

.session-delete {
  color: var(--el-text-color-placeholder);
  flex-shrink: 0;
}

.session-delete:hover { color: var(--el-color-danger); }
</style>
