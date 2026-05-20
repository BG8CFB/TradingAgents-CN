<template>
  <el-tag :type="tagType" size="small" round>
    {{ freshnessLabel }}
  </el-tag>
</template>

<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{
  status: string
  lastUpdated?: string | null
}>()

const tagType = computed(() => {
  if (props.status === 'fresh') return 'success'
  if (props.status === 'stale') return 'danger'
  if (props.status === 'refreshed') return ''
  if (props.status === 'unknown') return 'info'
  return 'warning'
})

const freshnessLabel = computed(() => {
  const map: Record<string, string> = {
    fresh: '新鲜',
    stale: '过期',
    refreshed: '已刷新',
    unknown: '未知',
    failed: '失败',
    timeout: '超时',
  }
  return map[props.status] || props.status
})
</script>
