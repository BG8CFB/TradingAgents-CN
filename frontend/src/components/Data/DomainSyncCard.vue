<template>
  <el-card shadow="hover" class="domain-sync-card" :class="{ 'is-syncing': syncing }">
    <div class="card-header">
      <span class="domain-name">{{ domainLabel }}</span>
      <el-tag :type="statusTagType" size="small">{{ statusText }}</el-tag>
    </div>
    <div class="card-body">
      <div class="stat-row">
        <span class="stat-label">最后同步</span>
        <span class="stat-value">{{ lastSyncDate || '暂无' }}</span>
      </div>
      <div class="stat-row">
        <span class="stat-label">记录数</span>
        <span class="stat-value">{{ recordCount }}</span>
      </div>
      <div class="card-footer">
        <el-button
          type="primary"
          size="small"
          :loading="syncing"
          @click="$emit('sync', domain)"
        >
          {{ syncing ? '同步中' : '增量同步' }}
        </el-button>
      </div>
    </div>
  </el-card>
</template>

<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{
  domain: string
  domainLabel: string
  lastSyncDate: string | null
  recordCount: number
  status: string
  syncing?: boolean
}>()

defineEmits<{
  sync: [domain: string]
}>()

const statusTagType = computed(() => {
  if (props.status === 'success') return 'success'
  if (props.status === 'failed') return 'danger'
  if (props.status === 'running') return 'warning'
  return 'info'
})

const statusText = computed(() => {
  const map: Record<string, string> = {
    success: '成功',
    failed: '失败',
    running: '运行中',
  }
  return map[props.status] || props.status
})
</script>

<style scoped>
.domain-sync-card {
  margin-bottom: 12px;
}
.domain-sync-card.is-syncing {
  border-color: #409eff;
}
.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
}
.domain-name {
  font-weight: bold;
  font-size: 14px;
}
.stat-row {
  display: flex;
  justify-content: space-between;
  margin-bottom: 8px;
}
.stat-label {
  color: #909399;
  font-size: 13px;
}
.stat-value {
  font-size: 13px;
}
.card-footer {
  margin-top: 12px;
}
</style>
