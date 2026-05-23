<template>
  <div class="market-dashboard" v-loading="loading">
    <!-- 数据源健康状态 -->
    <el-card shadow="hover" class="dashboard-card">
      <template #header>
        <div class="card-header">
          <span class="header-title">
            <el-icon><Monitor /></el-icon>
            数据源健康
          </span>
          <el-button size="small" :loading="loading" @click="loadData" link type="primary">
            <el-icon><Refresh /></el-icon>
            刷新
          </el-button>
        </div>
      </template>

      <div v-if="healthData.length > 0" class="health-grid">
        <div
          v-for="item in healthData"
          :key="`${item.source}-${item.domain}`"
          class="health-card"
          :class="getHealthClass(item.circuit_state)"
        >
          <div class="health-header">
            <span class="source-name">{{ item.source.toUpperCase() }}</span>
            <el-tag :type="circuitTagType(item.circuit_state)" size="small" effect="dark">
              {{ circuitLabel(item.circuit_state) }}
            </el-tag>
          </div>
          <div class="health-domain">{{ domainLabel(item.domain) }}</div>
          <div class="health-stats">
            <div class="stat">
              <span class="stat-value">{{ formatPercent(item.success_rate_1h) }}</span>
              <span class="stat-label">成功率</span>
            </div>
            <div class="stat">
              <span class="stat-value">{{ item.avg_latency_1h }}ms</span>
              <span class="stat-label">延迟</span>
            </div>
            <div class="stat">
              <span class="stat-value" :class="{ 'text-danger': item.consecutive_failures > 0 }">
                {{ item.consecutive_failures }}
              </span>
              <span class="stat-label">连续失败</span>
            </div>
          </div>
          <el-button
            v-if="item.circuit_state !== 'closed'"
            type="warning"
            size="small"
            plain
            @click="handleReset(item)"
            style="width: 100%; margin-top: 8px"
          >
            重置熔断器
          </el-button>
        </div>
      </div>
      <el-empty v-else description="暂无数据源健康信息" />
    </el-card>

    <!-- 数据域覆盖率 -->
    <el-card shadow="hover" class="dashboard-card" style="margin-top: 20px">
      <template #header>
        <div class="card-header">
          <span class="header-title">
            <el-icon><DataAnalysis /></el-icon>
            数据域覆盖
          </span>
        </div>
      </template>

      <div class="domain-grid">
        <div v-for="(stat, domain) in domainStats" :key="domain" class="domain-card" shadow="hover">
          <div class="domain-name">{{ domainLabel(domain as string) }}</div>
          <div class="domain-records">
            <span class="record-count">{{ stat.records }}</span>
            <span class="record-label">条记录</span>
          </div>
          <div class="domain-updated">
            {{ stat.last_updated ? formatTime(stat.last_updated) : '暂无数据' }}
          </div>
        </div>
      </div>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { Monitor, Refresh, DataAnalysis } from '@element-plus/icons-vue'
import {
  getDashboard, resetCircuitBreaker,
  type SourceHealthItem, type DomainStat,
  DOMAIN_LABELS,
} from '@/api/marketData'
import type { MarketCode } from '@/api/marketData'

const props = defineProps<{ market: MarketCode }>()

const loading = ref(false)
const healthData = ref<SourceHealthItem[]>([])
const domainStats = ref<Record<string, DomainStat>>({})

function domainLabel(domain: string) { return DOMAIN_LABELS[domain] || domain }
function formatPercent(v: number) { return (v * 100).toFixed(1) + '%' }
function formatTime(iso: string) { return iso ? new Date(iso).toLocaleString('zh-CN') : '' }
function circuitTagType(state: string) {
  if (state === 'closed') return 'success'
  if (state === 'open') return 'danger'
  return 'warning'
}
function circuitLabel(state: string) {
  const map: Record<string, string> = { closed: '正常', open: '熔断', half_open: '半开' }
  return map[state] || state
}
function getHealthClass(state: string) {
  if (state === 'closed') return 'health-good'
  if (state === 'open') return 'health-bad'
  return 'health-warn'
}

async function loadData() {
  loading.value = true
  try {
    const res = await getDashboard(props.market)
    if (res.success) {
      healthData.value = res.data?.source_health || []
      domainStats.value = res.data?.domain_stats || {}
    }
  } catch {
    ElMessage.error('加载看板数据失败')
  } finally {
    loading.value = false
  }
}

async function handleReset(row: SourceHealthItem) {
  try {
    await resetCircuitBreaker(props.market, row.source, row.domain)
    ElMessage.success('熔断器已重置')
    loadData()
  } catch {
    ElMessage.error('重置失败')
  }
}

onMounted(loadData)
</script>

<style scoped lang="scss">
.market-dashboard {
  .dashboard-card {
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

  .health-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(240px, 1fr));
    gap: 12px;
  }

  .health-card {
    padding: 16px;
    border-radius: 10px;
    border: 1px solid var(--el-border-color-lighter);
    transition: all 0.2s ease;

    &.health-good { background: var(--el-color-success-light-9); border-color: var(--el-color-success-light-7); }
    &.health-bad { background: var(--el-color-danger-light-9); border-color: var(--el-color-danger-light-7); }
    &.health-warn { background: var(--el-color-warning-light-9); border-color: var(--el-color-warning-light-7); }
    &:hover { box-shadow: 0 2px 12px rgba(0,0,0,0.08); }

    .health-header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      margin-bottom: 4px;
      .source-name { font-weight: 700; font-size: 14px; }
    }
    .health-domain {
      font-size: 12px;
      color: var(--el-text-color-secondary);
      margin-bottom: 12px;
    }
    .health-stats {
      display: flex;
      gap: 16px;
      .stat {
        text-align: center;
        .stat-value { display: block; font-size: 16px; font-weight: 600; color: var(--el-text-color-primary); }
        .stat-label { display: block; font-size: 11px; color: var(--el-text-color-secondary); margin-top: 2px; }
      }
    }
  }

  .domain-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(160px, 1fr));
    gap: 12px;
  }

  .domain-card {
    text-align: center;
    padding: 16px 12px;
    border-radius: 10px;
    border: 1px solid var(--el-border-color-lighter);
    background: var(--el-fill-color-lighter);
    transition: all 0.2s ease;
    &:hover { background: var(--el-color-primary-light-9); border-color: var(--el-color-primary-light-7); }

    .domain-name { font-weight: 600; margin-bottom: 8px; font-size: 13px; }
    .domain-records {
      .record-count { font-size: 24px; font-weight: 700; color: var(--el-color-primary); }
      .record-label { font-size: 12px; color: var(--el-text-color-secondary); margin-left: 4px; }
    }
    .domain-updated { font-size: 11px; color: var(--el-text-color-placeholder); margin-top: 6px; }
  }

  .text-danger { color: var(--el-color-danger) !important; }
}
</style>
