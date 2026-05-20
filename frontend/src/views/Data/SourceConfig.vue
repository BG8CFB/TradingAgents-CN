<template>
  <div class="source-config" v-loading="loading">
    <el-card header="数据源能力矩阵">
      <el-table :data="matrixRows" stripe>
        <el-table-column prop="domain" label="数据域" width="160" />
        <el-table-column label="Tushare" width="120">
          <template #default="{ row }">
            <el-tag :type="supportTag(row.tushare)" size="small">{{ row.tushare }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="AKShare" width="120">
          <template #default="{ row }">
            <el-tag :type="supportTag(row.akshare)" size="small">{{ row.akshare }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="BaoStock" width="120">
          <template #default="{ row }">
            <el-tag :type="supportTag(row.baostock)" size="small">{{ row.baostock }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="默认优先级" min-width="200">
          <template #default="{ row }">
            <span>{{ row.priority.join(' → ') }}</span>
          </template>
        </el-table-column>
      </el-table>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { getSourceConfig } from '@/api/cnData'

const loading = ref(false)
const matrixRows = ref<any[]>([])

function supportTag(level: string) {
  if (level === 'full') return 'success'
  if (level === 'partial') return 'warning'
  return 'info'
}

const domainLabels: Record<string, string> = {
  basic_info: '基础信息',
  daily_quotes: '日K线',
  daily_indicators: '每日指标',
  adj_factors: '复权因子',
  financial: '财务数据',
  market_quotes: '实时行情',
  news: '新闻',
  trade_calendar: '交易日历',
}

async function loadConfig() {
  loading.value = true
  try {
    const res = await getSourceConfig()
    const matrix = res.data?.capability_matrix || {}
    const priority = res.data?.priorities || {}

    matrixRows.value = Object.entries(matrix).map(([domain, sources]) => ({
      domain: domainLabels[domain] || domain,
      tushare: (sources as any).tushare || 'none',
      akshare: (sources as any).akshare || 'none',
      baostock: (sources as any).baostock || 'none',
      priority: priority[domain] || [],
    }))
  } catch {
    // 静默
  } finally {
    loading.value = false
  }
}

onMounted(loadConfig)
</script>
