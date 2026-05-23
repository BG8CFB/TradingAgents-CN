<template>
  <div class="market-source-config" v-loading="loading">
    <el-card shadow="hover">
      <template #header>
        <div class="card-header">
          <span class="header-title">
            <el-icon><Connection /></el-icon>
            数据源能力矩阵
          </span>
          <el-button size="small" :loading="loading" @click="loadConfig" link type="primary">
            <el-icon><Refresh /></el-icon>
          </el-button>
        </div>
      </template>

      <el-table :data="matrixRows" stripe style="width: 100%">
        <el-table-column prop="domain" label="数据域" width="140">
          <template #default="{ row }">{{ domainLabel(row.domain) }}</template>
        </el-table-column>
        <el-table-column v-for="src in sourceColumns" :key="src" :label="src.toUpperCase()" width="120">
          <template #default="{ row }">
            <el-tag :type="supportTag(row[src])" size="small">{{ supportLabel(row[src]) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="默认优先级" min-width="200">
          <template #default="{ row }">
            <span>{{ (row.priority || []).join(' → ') || '无' }}</span>
          </template>
        </el-table-column>
      </el-table>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { Connection, Refresh } from '@element-plus/icons-vue'
import { getSourceConfig, DOMAIN_LABELS } from '@/api/marketData'
import type { MarketCode } from '@/api/marketData'

const props = defineProps<{ market: MarketCode }>()

const loading = ref(false)
const matrixRows = ref<any[]>([])
const sourceColumns = ref<string[]>([])

function domainLabel(domain: string) { return DOMAIN_LABELS[domain] || domain }
function supportTag(level: string) {
  if (level === 'full') return 'success'
  if (level === 'partial') return 'warning'
  return 'info'
}
function supportLabel(level: string) {
  if (level === 'full') return '完整'
  if (level === 'partial') return '部分'
  return '-'
}

async function loadConfig() {
  loading.value = true
  try {
    const res = await getSourceConfig(props.market)
    if (res.success) {
      const matrix = res.data?.capability_matrix || {}
      const priority = res.data?.priorities || {}

      const sources = new Set<string>()
      Object.values(matrix).forEach((srcs: any) => {
        Object.keys(srcs).forEach(s => sources.add(s))
      })
      sourceColumns.value = Array.from(sources)

      matrixRows.value = Object.entries(matrix).map(([domain, srcs]) => ({
        domain,
        ...srcs as Record<string, string>,
        priority: priority[domain] || [],
      }))
    }
  } catch { /* 静默 */ } finally {
    loading.value = false
  }
}

onMounted(loadConfig)
</script>

<style scoped lang="scss">
.market-source-config {
  .card-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    .header-title {
      display: flex;
      align-items: center;
      gap: 6px;
      font-weight: 600;
      font-size: 15px;
    }
  }
}
</style>
