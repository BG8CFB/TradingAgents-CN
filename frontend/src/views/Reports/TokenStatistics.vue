<template>
  <div class="token-statistics">
    <!-- 页面标题 -->
    <div class="page-header">
      <h1 class="page-title">
        <el-icon><Coin /></el-icon>
        Token使用统计
      </h1>
      <p class="page-description">
        Token使用情况、成本分析和统计图表
      </p>
    </div>

    <!-- 控制面板 -->
    <el-card class="control-panel" shadow="never">
      <el-row :gutter="24" align="middle">
        <el-col :span="6">
          <el-form-item label="统计时间范围">
            <el-select v-model="timeRange" @change="loadStatistics">
              <el-option label="今天" value="today" />
              <el-option label="最近7天" value="week" />
              <el-option label="最近30天" value="month" />
              <el-option label="最近90天" value="quarter" />
              <el-option label="全部" value="all" />
            </el-select>
          </el-form-item>
        </el-col>
        <el-col :span="6">
          <el-form-item label="供应商筛选">
            <el-select v-model="providerFilter" @change="loadStatistics" clearable>
              <el-option label="全部供应商" value="" />
              <el-option label="阿里百炼" value="dashscope" />
              <el-option label="OpenAI" value="openai" />
              <el-option label="Google" value="google" />
              <el-option label="DeepSeek" value="deepseek" />
            </el-select>
          </el-form-item>
        </el-col>
        <el-col :span="12">
          <div class="control-buttons">
            <el-button @click="loadStatistics" :loading="loading">
              <el-icon><Refresh /></el-icon>
              刷新数据
            </el-button>
            <el-button @click="exportData">
              <el-icon><Download /></el-icon>
              导出统计
            </el-button>
          </div>
        </el-col>
      </el-row>
    </el-card>

    <!-- 概览指标 -->
    <el-row :gutter="24" style="margin-top: 24px">
      <el-col :span="6">
        <el-card class="metric-card" shadow="never">
          <div class="metric-content">
            <div class="metric-value">{{ formatNumber(overview.totalRequests) }}</div>
            <div class="metric-label">总请求数</div>
            <div class="metric-change" :class="getChangeClass(overview.requestsChange)">
              {{ formatChange(overview.requestsChange) }}
            </div>
          </div>
        </el-card>
      </el-col>
      <el-col :span="6">
        <el-card class="metric-card" shadow="never">
          <div class="metric-content">
            <div class="metric-value">{{ formatNumber(overview.totalTokens) }}</div>
            <div class="metric-label">总Token数</div>
            <div class="metric-change" :class="getChangeClass(overview.tokensChange)">
              {{ formatChange(overview.tokensChange) }}
            </div>
          </div>
        </el-card>
      </el-col>
      <el-col :span="6">
        <el-card class="metric-card" shadow="never">
          <div class="metric-content">
            <div class="metric-value">¥{{ formatNumber(overview.totalCost) }}</div>
            <div class="metric-label">总成本</div>
            <div class="metric-change" :class="getChangeClass(overview.costChange)">
              {{ formatChange(overview.costChange) }}
            </div>
          </div>
        </el-card>
      </el-col>
      <el-col :span="6">
        <el-card class="metric-card" shadow="never">
          <div class="metric-content">
            <div class="metric-value">¥{{ formatNumber(overview.avgCostPerRequest) }}</div>
            <div class="metric-label">平均单次成本</div>
            <div class="metric-change" :class="getChangeClass(overview.avgCostChange)">
              {{ formatChange(overview.avgCostChange) }}
            </div>
          </div>
        </el-card>
      </el-col>
    </el-row>

    <!-- 图表区域 -->
    <el-row :gutter="24" style="margin-top: 24px">
      <!-- Token使用趋势 -->
      <el-col :span="12">
        <el-card class="chart-card" shadow="never">
          <template #header>
            <h3>📈 Token使用趋势</h3>
          </template>
          <div ref="tokenTrendChart" class="chart-container"></div>
        </el-card>
      </el-col>

      <!-- 成本分布 -->
      <el-col :span="12">
        <el-card class="chart-card" shadow="never">
          <template #header>
            <h3>💰 成本分布</h3>
          </template>
          <div ref="costDistributionChart" class="chart-container"></div>
        </el-card>
      </el-col>
    </el-row>

    <el-row :gutter="24" style="margin-top: 24px">
      <!-- 供应商统计 -->
      <el-col :span="12">
        <el-card class="chart-card" shadow="never">
          <template #header>
            <h3>🏢 供应商统计</h3>
          </template>
          <div ref="providerChart" class="chart-container"></div>
        </el-card>
      </el-col>

      <!-- 模型使用排行 -->
      <el-col :span="12">
        <el-card class="chart-card" shadow="never">
          <template #header>
            <h3>🏆 模型使用排行</h3>
          </template>
          <div class="model-ranking">
            <div
              v-for="(model, index) in modelRanking"
              :key="model.name"
              class="ranking-item"
            >
              <div class="rank-number">{{ index + 1 }}</div>
              <div class="model-info">
                <div class="model-name">{{ model.name }}</div>
                <div class="model-stats">
                  {{ formatNumber(model.requests) }} 次请求 · 
                  {{ formatNumber(model.tokens) }} Token · 
                  ¥{{ formatNumber(model.cost) }}
                </div>
              </div>
              <div class="usage-bar">
                <el-progress
                  :percentage="(model.requests / modelRanking[0].requests) * 100"
                  :show-text="false"
                  :stroke-width="6"
                />
              </div>
            </div>
          </div>
        </el-card>
      </el-col>
    </el-row>

    <!-- 详细记录表 -->
    <el-card class="records-table" shadow="never" style="margin-top: 24px">
      <template #header>
        <div class="table-header">
          <h3>📋 详细记录</h3>
          <el-input
            v-model="searchKeyword"
            placeholder="搜索股票代码或模型名称"
            style="width: 200px"
            @input="filterRecords"
          >
            <template #prefix>
              <el-icon><Search /></el-icon>
            </template>
          </el-input>
        </div>
      </template>

      <el-table
        :data="filteredRecords"
        v-loading="loading"
        style="width: 100%"
        :default-sort="{ prop: 'timestamp', order: 'descending' }"
      >
        <el-table-column prop="timestamp" label="时间" width="180" sortable>
          <template #default="{ row }">
            {{ formatDateTime(row.timestamp) }}
          </template>
        </el-table-column>
        <el-table-column prop="provider" label="供应商" width="100">
          <template #default="{ row }">
            <el-tag size="small">{{ getProviderName(row.provider) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="model" label="模型" width="150" />
        <el-table-column prop="stock_symbol" label="股票代码" width="100" />
        <el-table-column prop="prompt_tokens" label="输入Token" width="100" sortable />
        <el-table-column prop="completion_tokens" label="输出Token" width="100" sortable />
        <el-table-column prop="total_tokens" label="总Token" width="100" sortable />
        <el-table-column prop="cost" label="成本(¥)" width="100" sortable>
          <template #default="{ row }">
            ¥{{ formatNumber(row.cost) }}
          </template>
        </el-table-column>
        <el-table-column prop="duration" label="耗时(ms)" width="100" sortable />
        <el-table-column label="操作" width="100">
          <template #default="{ row }">
            <el-button size="small" @click="viewDetails(row)">
              详情
            </el-button>
          </template>
        </el-table-column>
      </el-table>

      <!-- 分页 -->
      <el-pagination
        v-if="totalRecords > 0"
        v-model:current-page="currentPage"
        v-model:page-size="pageSize"
        :total="totalRecords"
        :page-sizes="[10, 20, 50, 100]"
        layout="total, sizes, prev, pager, next, jumper"
        style="margin-top: 16px; text-align: right"
        @size-change="loadRecords"
        @current-change="loadRecords"
      />
    </el-card>

    <!-- 空状态 -->
    <el-empty
      v-if="!loading && overview.totalRequests === 0"
      description="暂无Token使用记录"
      :image-size="200"
    >
      <template #description>
        <div class="empty-description">
          <p>暂无Token使用记录</p>
          <div class="empty-tips">
            <h4>💡 如何开始记录Token使用？</h4>
            <ul>
              <li>进行股票分析：使用股票分析功能</li>
              <li>确保API配置：检查API密钥是否正确配置</li>
              <li>启用成本跟踪：在配置管理中启用Token成本跟踪</li>
            </ul>
          </div>
        </div>
      </template>
    </el-empty>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, onMounted, onBeforeUnmount } from 'vue'
import { ElMessage } from 'element-plus'
import {
  Coin,
  Refresh,
  Download,
  Search
} from '@element-plus/icons-vue'
import * as echarts from 'echarts'
import { getUsageStatistics, getUsageRecords } from '@/api/usage'

// 时间范围 → 天数映射
const timeRangeDays: Record<string, number> = {
  today: 1,
  week: 7,
  month: 30,
  quarter: 90,
  all: 365
}

// 响应式数据
const loading = ref(false)
const timeRange = ref('month')
const providerFilter = ref('')
const searchKeyword = ref('')
const currentPage = ref(1)
const pageSize = ref(20)
const totalRecords = ref(0)

// 图表引用和实例
const tokenTrendChart = ref()
const costDistributionChart = ref()
const providerChart = ref()
let chartInstances: echarts.ECharts[] = []

// 数据
const overview = reactive({
  totalRequests: 0,
  totalTokens: 0,
  totalCost: 0,
  avgCostPerRequest: 0,
  requestsChange: 0,
  tokensChange: 0,
  costChange: 0,
  avgCostChange: 0
})

const records = ref<any[]>([])
const filteredRecords = ref<any[]>([])
const modelRanking = ref<any[]>([])

// 方法
const formatNumber = (num: number): string => {
  if (!Number.isFinite(num)) return '0'
  if (num >= 1000000) {
    return (num / 1000000).toFixed(1) + 'M'
  } else if (num >= 1000) {
    return (num / 1000).toFixed(1) + 'K'
  }
  return num.toFixed(2)
}

const formatChange = (change: number): string => {
  if (!Number.isFinite(change)) return '0%'
  if (change > 0) return `+${change.toFixed(1)}%`
  if (change < 0) return `${change.toFixed(1)}%`
  return '0%'
}

const getChangeClass = (change: number): string => {
  if (change > 0) return 'positive'
  if (change < 0) return 'negative'
  return 'neutral'
}

const formatDateTime = (timestamp: string): string => {
  if (!timestamp) return '-'
  return new Date(timestamp).toLocaleString('zh-CN')
}

const getProviderName = (provider: string): string => {
  const names: Record<string, string> = {
    'dashscope': '阿里百炼',
    'openai': 'OpenAI',
    'google': 'Google',
    'deepseek': 'DeepSeek',
    'anthropic': 'Anthropic',
    'siliconflow': '硅基流动',
    'openrouter': 'OpenRouter'
  }
  return names[provider] || provider
}

// 加载统计数据（对接后端）
const loadStatistics = async () => {
  loading.value = true
  try {
    const days = timeRangeDays[timeRange.value] || 30
    const res: any = await getUsageStatistics({
      days,
      provider: providerFilter.value || undefined
    })
    const data = res?.data ?? res

    if (data) {
      overview.totalRequests = data.total_requests ?? 0
      overview.totalTokens = (data.total_input_tokens ?? 0) + (data.total_output_tokens ?? 0)
      overview.totalCost = data.total_cost ?? 0
      overview.avgCostPerRequest = overview.totalRequests > 0
        ? overview.totalCost / overview.totalRequests
        : 0
      // 后端暂不返回环比数据，保持为 0
      overview.requestsChange = 0
      overview.tokensChange = 0
      overview.costChange = 0
      overview.avgCostChange = 0

      // 构建模型排行
      if (data.by_model && typeof data.by_model === 'object') {
        modelRanking.value = Object.entries(data.by_model)
          .map(([name, info]: [string, any]) => ({
            name,
            requests: info?.total_requests ?? info?.count ?? 0,
            tokens: (info?.total_input_tokens ?? 0) + (info?.total_output_tokens ?? 0),
            cost: info?.total_cost ?? 0
          }))
          .sort((a, b) => b.requests - a.requests)
      } else {
        modelRanking.value = []
      }
    }

    // 并行加载图表数据
    await Promise.all([
      loadDailyCostChart(days),
      loadCostByProviderChart(days),
      loadProviderBarChart(days)
    ])
  } catch (error: any) {
    console.error('加载统计数据失败:', error)
    ElMessage.error('加载统计数据失败')
  } finally {
    loading.value = false
  }
}

// 加载使用记录（对接后端）
const loadRecords = async () => {
  try {
    const res: any = await getUsageRecords({
      provider: providerFilter.value || undefined,
      limit: pageSize.value
    })
    const data = res?.data ?? res

    if (data?.records) {
      records.value = data.records.map((r: any) => ({
        timestamp: r.timestamp ?? r.created_at,
        provider: r.provider,
        model: r.model_name ?? r.model,
        stock_symbol: r.session_id ?? r.analysis_type ?? '-',
        prompt_tokens: r.input_tokens ?? 0,
        completion_tokens: r.output_tokens ?? 0,
        total_tokens: (r.input_tokens ?? 0) + (r.output_tokens ?? 0),
        cost: r.cost ?? 0,
        duration: r.duration_ms ?? r.duration ?? 0
      }))
      totalRecords.value = data.total ?? records.value.length
    } else {
      records.value = []
      totalRecords.value = 0
    }
    filterRecords()
  } catch (error: any) {
    console.error('加载记录失败:', error)
    records.value = []
    totalRecords.value = 0
    filteredRecords.value = []
  }
}

// 加载每日成本趋势图
const loadDailyCostChart = async (days: number) => {
  if (!tokenTrendChart.value) return
  try {
    const res: any = await (await import('@/api/usage')).getDailyCost(days)
    const data = res?.data ?? res
    const items = Array.isArray(data) ? data : (data?.items ?? [])

    const dates = items.map((d: any) => d.date ?? d.day ?? '')
    const costs = items.map((d: any) => d.total_cost ?? d.cost ?? 0)
    const tokens = items.map((d: any) => d.total_tokens ?? d.tokens ?? 0)

    const chart = echarts.init(tokenTrendChart.value)
    chartInstances.push(chart)
    chart.setOption({
      tooltip: { trigger: 'axis' },
      legend: { data: ['成本 (¥)', 'Token 数'] },
      xAxis: { type: 'category', data: dates },
      yAxis: [
        { type: 'value', name: '成本 (¥)' },
        { type: 'value', name: 'Token' }
      ],
      series: [
        { name: '成本 (¥)', data: costs, type: 'line', smooth: true },
        { name: 'Token 数', data: tokens, type: 'line', smooth: true, yAxisIndex: 1 }
      ]
    })
  } catch {
    // 接口失败时渲染空图表
    if (tokenTrendChart.value) {
      const chart = echarts.init(tokenTrendChart.value)
      chartInstances.push(chart)
      chart.setOption({
        title: { text: '暂无数据', left: 'center', top: 'center', textStyle: { color: '#999', fontSize: 14 } },
        xAxis: { show: false },
        yAxis: { show: false },
        series: []
      })
    }
  }
}

// 加载成本分布饼图
const loadCostByProviderChart = async (days: number) => {
  if (!costDistributionChart.value) return
  try {
    const res: any = await (await import('@/api/usage')).getCostByProvider(days)
    const data = res?.data ?? res
    const items = Array.isArray(data) ? data : (data?.items ?? [])

    const pieData = items.map((d: any) => ({
      value: d.total_cost ?? d.cost ?? 0,
      name: getProviderName(d.provider ?? d.name ?? '')
    }))

    const chart = echarts.init(costDistributionChart.value)
    chartInstances.push(chart)
    chart.setOption({
      tooltip: { trigger: 'item', formatter: '{b}: ¥{c} ({d}%)' },
      series: [{
        type: 'pie',
        radius: ['40%', '70%'],
        data: pieData.length > 0 ? pieData : [{ value: 0, name: '暂无数据' }],
        emphasis: { itemStyle: { shadowBlur: 10, shadowOffsetX: 0, shadowColor: 'rgba(0,0,0,0.5)' } }
      }]
    })
  } catch {
    if (costDistributionChart.value) {
      const chart = echarts.init(costDistributionChart.value)
      chartInstances.push(chart)
      chart.setOption({
        title: { text: '暂无数据', left: 'center', top: 'center', textStyle: { color: '#999', fontSize: 14 } },
        series: []
      })
    }
  }
}

// 加载供应商柱状图
const loadProviderBarChart = async (days: number) => {
  if (!providerChart.value) return
  try {
    const res: any = await (await import('@/api/usage')).getCostByProvider(days)
    const data = res?.data ?? res
    const items = Array.isArray(data) ? data : (data?.items ?? [])

    const names = items.map((d: any) => getProviderName(d.provider ?? d.name ?? ''))
    const values = items.map((d: any) => d.total_requests ?? d.count ?? 0)

    const chart = echarts.init(providerChart.value)
    chartInstances.push(chart)
    chart.setOption({
      tooltip: { trigger: 'axis' },
      xAxis: { type: 'category', data: names },
      yAxis: { type: 'value', name: '请求数' },
      series: [{ data: values, type: 'bar' }]
    })
  } catch {
    if (providerChart.value) {
      const chart = echarts.init(providerChart.value)
      chartInstances.push(chart)
      chart.setOption({
        title: { text: '暂无数据', left: 'center', top: 'center', textStyle: { color: '#999', fontSize: 14 } },
        xAxis: { show: false },
        yAxis: { show: false },
        series: []
      })
    }
  }
}

const filterRecords = () => {
  if (!searchKeyword.value) {
    filteredRecords.value = records.value
  } else {
    const keyword = searchKeyword.value.toLowerCase()
    filteredRecords.value = records.value.filter(record =>
      (record.stock_symbol ?? '').toLowerCase().includes(keyword) ||
      (record.model ?? '').toLowerCase().includes(keyword)
    )
  }
}

const exportData = () => {
  ElMessage.info('导出功能开发中...')
}

const viewDetails = (_row: any) => {
  ElMessage.info('详情功能开发中...')
}

// 生命周期
onMounted(async () => {
  await loadStatistics()
  await loadRecords()
})

onBeforeUnmount(() => {
  chartInstances.forEach(c => c.dispose())
  chartInstances = []
})
</script>

<style lang="scss" scoped>
.token-statistics {
  .page-header {
    margin-bottom: 24px;

    .page-title {
      display: flex;
      align-items: center;
      gap: 8px;
      font-size: 24px;
      font-weight: 600;
      color: var(--el-text-color-primary);
      margin: 0 0 8px 0;
    }

    .page-description {
      color: var(--el-text-color-regular);
      margin: 0;
    }
  }

  .control-panel {
    .control-buttons {
      display: flex;
      gap: 12px;
      justify-content: flex-end;
    }
  }

  .metric-card {
    .metric-content {
      text-align: center;
      
      .metric-value {
        font-size: 28px;
        font-weight: 600;
        color: var(--el-color-primary);
        margin-bottom: 8px;
      }
      
      .metric-label {
        font-size: 14px;
        color: var(--el-text-color-regular);
        margin-bottom: 4px;
      }
      
      .metric-change {
        font-size: 12px;
        
        &.positive {
          color: var(--el-color-success);
        }
        
        &.negative {
          color: var(--el-color-danger);
        }
        
        &.neutral {
          color: var(--el-text-color-placeholder);
        }
      }
    }
  }

  .chart-card {
    .chart-container {
      height: 300px;
    }
    
    .model-ranking {
      .ranking-item {
        display: flex;
        align-items: center;
        padding: 12px 0;
        border-bottom: 1px solid var(--el-border-color-lighter);
        
        &:last-child {
          border-bottom: none;
        }
        
        .rank-number {
          width: 32px;
          height: 32px;
          border-radius: 50%;
          background: var(--el-color-primary);
          color: white;
          display: flex;
          align-items: center;
          justify-content: center;
          font-weight: 600;
          margin-right: 12px;
        }
        
        .model-info {
          flex: 1;
          
          .model-name {
            font-weight: 600;
            margin-bottom: 4px;
          }
          
          .model-stats {
            font-size: 12px;
            color: var(--el-text-color-regular);
          }
        }
        
        .usage-bar {
          width: 100px;
        }
      }
    }
  }

  .records-table {
    .table-header {
      display: flex;
      justify-content: space-between;
      align-items: center;
      
      h3 {
        margin: 0;
      }
    }
  }

  .empty-description {
    .empty-tips {
      margin-top: 16px;
      text-align: left;
      
      h4 {
        margin: 0 0 8px 0;
        color: var(--el-text-color-primary);
      }
      
      ul {
        margin: 0;
        padding-left: 20px;
        
        li {
          margin-bottom: 4px;
          color: var(--el-text-color-regular);
        }
      }
    }
  }
}
</style>
