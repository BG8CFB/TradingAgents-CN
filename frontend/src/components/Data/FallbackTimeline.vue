<template>
  <el-timeline v-if="events.length > 0">
    <el-timeline-item
      v-for="(event, index) in events"
      :key="index"
      :timestamp="formatTime(event.updated_at)"
      :type="event.event_type === 'SOURCE_FALLBACK' ? 'warning' : event.event_type === 'CIRCUIT_OPEN' ? 'danger' : 'primary'"
      placement="top"
    >
      <el-card shadow="hover" class="timeline-card">
        <div class="timeline-header">
          <el-tag :type="eventTypeTag(event.event_type)" size="small">
            {{ eventTypeLabel(event.event_type) }}
          </el-tag>
          <span class="timeline-domain">{{ event.domain }}</span>
        </div>
        <div class="timeline-body" v-if="event.fallback_from">
          <span class="fallback-text">
            从 <strong>{{ event.fallback_from }}</strong> 降级到 <strong>{{ event.source }}</strong>
          </span>
        </div>
        <div class="timeline-body" v-if="event.error_message">
          <span class="error-text">{{ event.error_message }}</span>
        </div>
      </el-card>
    </el-timeline-item>
  </el-timeline>
  <el-empty v-else description="暂无回退事件" />
</template>

<script setup lang="ts">
export interface FallbackEvent {
  event_type: string
  domain: string
  source: string
  fallback_from: string | null
  error_message: string | null
  updated_at: string
}

defineProps<{
  events: FallbackEvent[]
}>()

function formatTime(iso: string) {
  if (!iso) return ''
  return new Date(iso).toLocaleString('zh-CN')
}

function eventTypeTag(type: string) {
  if (type === 'SOURCE_FALLBACK') return 'warning'
  if (type === 'CIRCUIT_OPEN') return 'danger'
  if (type === 'CIRCUIT_CLOSE') return 'success'
  return 'info'
}

function eventTypeLabel(type: string) {
  const map: Record<string, string> = {
    SOURCE_FALLBACK: '数据源降级',
    CIRCUIT_OPEN: '熔断器打开',
    CIRCUIT_CLOSE: '熔断器恢复',
    SYNC_FAILED: '同步失败',
    SYNC_SUCCESS: '同步成功',
  }
  return map[type] || type
}
</script>

<style scoped>
.timeline-card {
  margin-bottom: 0;
}
.timeline-header {
  display: flex;
  align-items: center;
  gap: 8px;
}
.timeline-domain {
  font-weight: bold;
  font-size: 13px;
}
.timeline-body {
  margin-top: 4px;
  font-size: 12px;
}
.fallback-text {
  color: #e6a23c;
}
.error-text {
  color: #f56c6c;
}
</style>
