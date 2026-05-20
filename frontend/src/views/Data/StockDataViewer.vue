<template>
  <div class="stock-data-viewer">
    <el-card header="股票数据查看">
      <el-form inline class="mb-4">
        <el-form-item label="股票代码">
          <el-input v-model="symbol" placeholder="输入股票代码" style="width: 160px" />
        </el-form-item>
        <el-form-item label="数据域">
          <el-select v-model="domain" clearable placeholder="全部">
            <el-option label="基础信息" value="basic_info" />
            <el-option label="日K线" value="daily_quotes" />
            <el-option label="每日指标" value="daily_indicators" />
            <el-option label="复权因子" value="adj_factors" />
            <el-option label="财务数据" value="financial" />
            <el-option label="新闻" value="news" />
          </el-select>
        </el-form-item>
        <el-form-item label="日期范围">
          <el-date-picker
            v-model="dateRange"
            type="daterange"
            range-separator="-"
            start-placeholder="开始日期"
            end-placeholder="结束日期"
            value-format="YYYY-MM-DD"
          />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" :loading="loading" @click="loadData">
            查询
          </el-button>
          <el-button @click="handleRefresh">
            刷新数据
          </el-button>
        </el-form-item>
      </el-form>

      <!-- 新鲜度状态 -->
      <div v-if="freshness.domains" class="mb-4">
        <span v-for="(status, d) in freshness.domains" :key="d" class="mr-2">
          <el-tag :type="status === 'fresh' ? 'success' : status === 'stale' ? 'danger' : 'info'" size="small">
            {{ d }}: {{ status }}
          </el-tag>
        </span>
      </div>

      <!-- 数据展示 -->
      <el-tabs v-model="activeDomain">
        <el-tab-pane
          v-for="(data, d) in stockData"
          :key="d"
          :label="domainLabel(d)"
          :name="d"
        >
          <div v-if="data.error" class="error-text">{{ data.error }}</div>
          <div v-else>
            <div class="mb-2">共 {{ data.total }} 条记录</div>
            <el-table :data="data.items" stripe max-height="500" size="small">
              <el-table-column
                v-for="col in tableColumns(data.items)"
                :key="col"
                :prop="col"
                :label="col"
                min-width="120"
                show-overflow-tooltip
              />
            </el-table>
          </div>
        </el-tab-pane>
      </el-tabs>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { ElMessage } from 'element-plus'
import { getStockData, refreshStock, getRefreshStatus } from '@/api/cnData'

const symbol = ref('000001')
const domain = ref('')
const dateRange = ref<string[]>([])
const loading = ref(false)
const activeDomain = ref('')
const stockData = ref<Record<string, any>>({})
const freshness = ref<any>({})

const domainLabels: Record<string, string> = {
  basic_info: '基础信息',
  daily_quotes: '日K线',
  daily_indicators: '每日指标',
  adj_factors: '复权因子',
  financial: '财务数据',
  news: '新闻',
}

function domainLabel(d: string) {
  return domainLabels[d] || d
}

function tableColumns(items: any[]) {
  if (!items || items.length === 0) return []
  const keys = new Set<string>()
  items.slice(0, 5).forEach(item => Object.keys(item).forEach(k => keys.add(k)))
  return Array.from(keys).filter(k => k !== '_id')
}

async function loadData() {
  if (!symbol.value) return
  loading.value = true
  try {
    const params: any = {}
    if (domain.value) params.domain = domain.value
    if (dateRange.value?.[0]) params.start_date = dateRange.value[0]
    if (dateRange.value?.[1]) params.end_date = dateRange.value[1]

    const res = await getStockData(symbol.value, params)
    stockData.value = res.data || {}

    // 设置默认活跃标签
    const domains = Object.keys(stockData.value)
    if (domains.length > 0 && !activeDomain.value) {
      activeDomain.value = domains[0]
    }

    // 加载新鲜度
    try {
      const freshRes = await getRefreshStatus(symbol.value)
      freshness.value = freshRes.data || {}
    } catch {
      // 非关键
    }
  } catch {
    ElMessage.error('查询数据失败')
  } finally {
    loading.value = false
  }
}

async function handleRefresh() {
  if (!symbol.value) return
  try {
    await refreshStock(symbol.value)
    ElMessage.success('刷新任务已触发')
    setTimeout(loadData, 2000)
  } catch {
    ElMessage.error('刷新失败')
  }
}
</script>

<style scoped>
.mb-2 { margin-bottom: 8px; }
.mb-4 { margin-bottom: 16px; }
.mr-2 { margin-right: 8px; }
.error-text { color: #f56c6c; }
</style>
