<template>
  <div class="market-stock-viewer">
    <el-card shadow="hover">
      <template #header>
        <div class="card-header">
          <span class="header-title">
            <el-icon><Search /></el-icon>
            股票数据查看
          </span>
        </div>
      </template>

      <el-form inline style="margin-bottom: 16px">
        <el-form-item label="股票代码">
          <el-input v-model="symbol" placeholder="输入股票代码" style="width: 160px" @keyup.enter="handleSearch" />
        </el-form-item>
        <el-form-item label="数据域">
          <el-select v-model="selectedDomain" clearable placeholder="全部域" style="width: 160px">
            <el-option v-for="d in domainOptions" :key="d.value" :label="d.label" :value="d.value" />
          </el-select>
        </el-form-item>
        <el-form-item>
          <el-button type="primary" :loading="loading" @click="handleSearch">查询</el-button>
        </el-form-item>
      </el-form>

      <div v-if="stockData" class="stock-result">
        <div v-for="(domainResult, domain) in (stockData as Record<string, any>)" :key="domain" class="domain-result">
          <h4 class="domain-title">{{ domainLabel(domain) }}
            <el-tag size="small" type="info">{{ domainResult.total }} 条</el-tag>
          </h4>
          <div v-if="domainResult.error" class="domain-error">
            <el-alert :title="domainResult.error" type="error" :closable="false" show-icon />
          </div>
          <el-table v-else :data="domainResult.items || []" stripe size="small" max-height="300">
            <el-table-column
              v-for="col in getColumns(domainResult.items?.[0])"
              :key="col"
              :prop="col"
              :label="col"
              min-width="120"
              show-overflow-tooltip
            />
          </el-table>
        </div>
      </div>
      <el-empty v-else-if="searched" description="暂无数据" />
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import { Search } from '@element-plus/icons-vue'
import { getStockData, DOMAIN_LABELS } from '@/api/marketData'
import type { MarketCode } from '@/api/marketData'

const props = defineProps<{ market: MarketCode }>()

const symbol = ref('')
const selectedDomain = ref<string | undefined>(undefined)
const loading = ref(false)
const searched = ref(false)
const stockData = ref<any>(null)

const domainOptions = computed(() => [
  { value: 'basic_info', label: '基础信息' },
  { value: 'daily_quotes', label: '日K线' },
  { value: 'daily_indicators', label: '每日指标' },
  { value: 'adj_factors', label: '复权因子' },
  { value: 'financial_data', label: '财务数据' },
  { value: 'news', label: '新闻' },
])

function domainLabel(domain: string) { return DOMAIN_LABELS[domain] || domain }
function getColumns(firstItem: any) {
  if (!firstItem || typeof firstItem !== 'object') return []
  return Object.keys(firstItem).filter(k => !['_id', 'id'].includes(k))
}

async function handleSearch() {
  if (!symbol.value) return
  loading.value = true
  searched.value = true
  try {
    const res = await getStockData(props.market, symbol.value, {
      domain: selectedDomain.value,
      page: 1,
      page_size: 20,
    })
    if (res.success) {
      stockData.value = res.data
    } else {
      stockData.value = null
    }
  } catch {
    stockData.value = null
  } finally {
    loading.value = false
  }
}
</script>

<style scoped lang="scss">
.market-stock-viewer {
  .card-header {
    .header-title {
      display: flex;
      align-items: center;
      gap: 6px;
      font-weight: 600;
      font-size: 15px;
    }
  }

  .stock-result {
    .domain-result {
      margin-bottom: 20px;
      &:last-child { margin-bottom: 0; }

      .domain-title {
        display: flex;
        align-items: center;
        gap: 8px;
        margin: 0 0 12px 0;
        font-size: 14px;
        font-weight: 600;
      }
      .domain-error { margin-top: 8px; }
    }
  }
}
</style>
