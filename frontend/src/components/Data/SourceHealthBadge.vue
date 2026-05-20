<template>
  <el-tag :type="tagType" size="small" effect="dark">
    <span class="badge-content">
      {{ source }}
      <span class="badge-detail" v-if="detail"> | {{ detail }}</span>
    </span>
  </el-tag>
</template>

<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{
  source: string
  circuitState?: string
  successRate?: number
  latency?: number
}>()

const tagType = computed(() => {
  if (props.circuitState === 'open') return 'danger'
  if (props.circuitState === 'half_open') return 'warning'
  if (props.successRate !== undefined && props.successRate < 0.5) return 'danger'
  return 'success'
})

const detail = computed(() => {
  const parts: string[] = []
  if (props.successRate !== undefined) {
    parts.push(`${(props.successRate * 100).toFixed(0)}%`)
  }
  if (props.latency !== undefined) {
    parts.push(`${props.latency}ms`)
  }
  return parts.join(' ')
})
</script>

<style scoped>
.badge-content {
  font-size: 12px;
}
.badge-detail {
  opacity: 0.8;
  font-size: 11px;
}
</style>
