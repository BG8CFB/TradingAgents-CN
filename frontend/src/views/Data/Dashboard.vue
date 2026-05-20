<template>
  <div class="dashboard" v-loading="loading">
    <!-- 源健康状态 -->
    <el-card header="数据源健康" class="mb-4">
      <el-table :data="healthData" stripe>
        <el-table-column prop="source" label="数据源" width="120" />
        <el-table-column prop="domain" label="数据域" width="160" />
        <el-table-column label="熔断状态" width="120">
          <template #default="{ row }">
            <el-tag :type="circuitTagType(row.circuit_state)" size="small">
              {{ row.circuit_state }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="success_rate_1h" label="成功率" width="100">
          <template #default="{ row }">
            {{ (row.success_rate_1h * 100).toFixed(1) }}%
          </template>
        </el-table-column>
        <el-table-column prop="avg_latency_1h" label="平均延迟(ms)" width="120" />
        <el-table-column prop="consecutive_failures" label="连续失败" width="100" />
        <el-table-column label="操作" width="100">
          <template #default="{ row }">
            <el-button
              v-if="row.circuit_state !== 'closed'"
              type="warning"
              size="small"
              @click="handleReset(row)"
            >
              重置
            </el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <!-- 域覆盖率 -->
    <el-card header="数据域覆盖">
      <el-row :gutter="16">
        <el-col :span="6" v-for="(stat, domain) in domainStats" :key="domain">
          <el-card shadow="hover" class="domain-card">
            <div class="domain-name">{{ domainLabel(domain) }}</div>
            <div class="domain-count">{{ stat.records }} 条</div>
            <div class="domain-updated">
              {{ stat.last_updated ? formatTime(stat.last_updated) : '暂无数据' }}
            </div>
          </el-card>
        </el-col>
      </el-row>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { getDashboard, resetCircuitBreaker, type SourceHealthItem, type DomainStat } from '@/api/cnData'

const loading = ref(false)
const healthData = ref<SourceHealthItem[]>([])
const domainStats = ref<Record<string, DomainStat>>({})

const domainLabels: Record<string, string> = {
  basic_info: '基础信息',
  daily_quotes: '日K线',
  daily_indicators: '每日指标',
  adj_factors: '复权因子',
  financial: '财务数据',
  market_quotes: '实时行情',
  news: '新闻',
}

function domainLabel(domain: string) {
  return domainLabels[domain] || domain
}

function circuitTagType(state: string) {
  if (state === 'closed') return 'success'
  if (state === 'open') return 'danger'
  return 'warning'
}

function formatTime(iso: string) {
  if (!iso) return ''
  return new Date(iso).toLocaleString('zh-CN')
}

async function loadData() {
  loading.value = true
  try {
    const res = await getDashboard()
    healthData.value = res.data?.source_health || []
    domainStats.value = res.data?.domain_stats || {}
  } catch (e: any) {
    ElMessage.error('加载看板数据失败')
  } finally {
    loading.value = false
  }
}

async function handleReset(row: SourceHealthItem) {
  try {
    await resetCircuitBreaker(row.source, row.domain)
    ElMessage.success('熔断器已重置')
    loadData()
  } catch (e: any) {
    ElMessage.error('重置失败')
  }
}

onMounted(loadData)
</script>

<style scoped>
.domain-card {
  text-align: center;
  margin-bottom: 16px;
}
.domain-name {
  font-weight: bold;
  margin-bottom: 8px;
}
.domain-count {
  font-size: 24px;
  color: #409eff;
}
.domain-updated {
  font-size: 12px;
  color: #909399;
  margin-top: 4px;
}
.mb-4 {
  margin-bottom: 16px;
}
</style>
