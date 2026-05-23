<template>
  <div class="market-quality" v-loading="loading">
    <el-card shadow="hover">
      <template #header>
        <div class="card-header">
          <span class="header-title">
            <el-icon><DataAnalysis /></el-icon>
            数据质量总览
          </span>
          <el-button size="small" :loading="loading" @click="loadQuality" link type="primary">
            <el-icon><Refresh /></el-icon>
          </el-button>
        </div>
      </template>

      <div class="quality-grid">
        <div v-for="(info, domain) in (qualityData as Record<string, any>)" :key="domain" class="quality-card">
          <div class="quality-domain">{{ domainLabel(domain as string) }}</div>
          <div class="quality-stat">
            <span class="stat-label">总记录:</span>
            <span class="stat-value">{{ info.total_records ?? 0 }}</span>
          </div>
          <el-progress
            :percentage="Math.round((info.completeness ?? 0) * 100)"
            :status="(info.completeness ?? 0) >= 0.99 ? 'success' : 'warning'"
            :stroke-width="10"
            style="margin-top: 8px"
          />
          <div v-if="info.error" class="quality-error">{{ info.error }}</div>
        </div>
      </div>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { DataAnalysis, Refresh } from '@element-plus/icons-vue'
import { getQualityOverview, DOMAIN_LABELS } from '@/api/marketData'
import type { MarketCode } from '@/api/marketData'

const props = defineProps<{ market: MarketCode }>()
const loading = ref(false)
const qualityData = ref<any>({})

function domainLabel(domain: string) { return DOMAIN_LABELS[domain] || domain }

async function loadQuality() {
  loading.value = true
  try {
    const res = await getQualityOverview(props.market)
    if (res.success) qualityData.value = res.data || {}
  } catch { /* 静默 */ } finally {
    loading.value = false
  }
}

onMounted(loadQuality)
</script>

<style scoped lang="scss">
.market-quality {
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

  .quality-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
    gap: 16px;
  }

  .quality-card {
    text-align: center;
    padding: 20px 16px;
    border-radius: 10px;
    border: 1px solid var(--el-border-color-lighter);
    background: var(--el-fill-color-lighter);
    transition: all 0.2s ease;
    &:hover { background: var(--el-color-primary-light-9); border-color: var(--el-color-primary-light-7); }

    .quality-domain { font-weight: 600; margin-bottom: 12px; font-size: 14px; }
    .quality-stat {
      margin-bottom: 4px;
      .stat-label { color: var(--el-text-color-secondary); font-size: 13px; }
      .stat-value { font-weight: 700; font-size: 13px; }
    }
    .quality-error { color: var(--el-color-danger); font-size: 12px; margin-top: 8px; }
  }
}
</style>
