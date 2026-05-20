<template>
  <div class="data-quality" v-loading="loading">
    <el-card header="数据质量总览">
      <el-row :gutter="16">
        <el-col :span="6" v-for="(info, domain) in (qualityData as Record<string, any>)" :key="domain">
          <el-card shadow="hover" class="quality-card">
            <div class="domain-name">{{ domainLabel(domain) }}</div>
            <div class="stat-row">
              <span class="stat-label">总记录:</span>
              <span class="stat-value">{{ info.total_records }}</span>
            </div>
            <div class="stat-row">
              <span class="stat-label">完整度:</span>
              <el-progress
                :percentage="Math.round((info.completeness as number) * 100)"
                :status="(info.completeness as number) >= 0.99 ? 'success' : 'warning'"
                :stroke-width="10"
              />
            </div>
            <div v-if="info.error" class="error-text">{{ info.error }}</div>
          </el-card>
        </el-col>
      </el-row>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { getQualityOverview } from '@/api/cnData'

const loading = ref(false)
const qualityData = ref<any>({})

const domainLabels: Record<string, string> = {
  daily_quotes: '日K线',
  daily_indicators: '每日指标',
  financial: '财务数据',
  basic_info: '基础信息',
}

function domainLabel(domain: string) {
  return domainLabels[domain] || domain
}

async function loadQuality() {
  loading.value = true
  try {
    const res = await getQualityOverview()
    qualityData.value = res.data || {}
  } catch {
    // 静默
  } finally {
    loading.value = false
  }
}

onMounted(loadQuality)
</script>

<style scoped>
.quality-card {
  text-align: center;
  margin-bottom: 16px;
}
.domain-name {
  font-weight: bold;
  margin-bottom: 12px;
}
.stat-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 8px;
}
.stat-label {
  color: #909399;
}
.stat-value {
  font-weight: bold;
}
.error-text {
  color: #f56c6c;
  font-size: 12px;
}
</style>
