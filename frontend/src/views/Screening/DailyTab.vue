<template>
  <div class="daily-tab" :aria-busy="loading">
    <div class="daily-toolbar">
      <div class="trade-date" aria-live="polite">
        <span v-if="data?.trade_date">推荐数据截至 {{ data.trade_date }}</span>
        <span v-else-if="data?.factor_trade_date">可用因子截至 {{ data.factor_trade_date }}</span>
        <span v-else>数据日期待确认</span>
        <span v-if="data?.trade_date && data.factor_trade_date && data.factor_trade_date !== data.trade_date" class="factor-date">
          最新因子批次 {{ data.factor_trade_date }}
        </span>
      </div>
      <el-button link :loading="loading" @click="load">
        <el-icon><Refresh /></el-icon>
        刷新
      </el-button>
    </div>

    <div v-if="loading" class="loading-state" role="status">
      <p>正在读取已生成的推荐结果…</p>
      <el-skeleton :rows="4" animated />
    </div>

    <el-result v-else-if="loadError" icon="error" title="获取推荐失败" :sub-title="loadError">
      <template #extra>
        <el-button type="primary" @click="load">重试查询</el-button>
      </template>
    </el-result>

    <template v-else-if="data">
    <el-alert
      v-if="freshnessNotice"
      class="status-alert"
      :title="freshnessNotice.title"
      :description="freshnessNotice.description"
      :type="freshnessNotice.type"
      :closable="false"
      show-icon
    />

    <el-empty
      v-if="strategies.length === 0"
      :image-size="160"
    >
      <template #description>
        <p class="empty-title">{{ emptyNotice.title }}</p>
        <p class="empty-desc">{{ emptyNotice.description }}</p>
      </template>
      <el-button type="primary" @click="goDataCenter">前往数据中心</el-button>
      <el-button v-if="authStore.isAdmin && data.status !== 'no_factor_data'" @click="goScheduler">检查调度任务</el-button>
    </el-empty>

    <el-collapse v-else v-model="activeNames">
      <el-collapse-item
        v-for="s in strategies"
        :key="s.strategy_id"
        :name="s.strategy_id"
      >
        <template #title>
          <div class="collapse-title">
            <span class="name">{{ s.strategy_name || s.strategy_id }}</span>
            <el-tag size="small" type="info" effect="plain">{{ s.total ?? s.items.length }} 只入选</el-tag>
            <el-tag size="small" :type="qualityTagType(s)" effect="plain">{{ qualityLabel(s) }}</el-tag>
            <el-tag
              v-if="s.insight_status === 'done'"
              size="small"
              type="success"
              effect="plain"
            >
              AI 短评已生成
            </el-tag>
            <el-tag
              v-else-if="s.insight_status === 'failed'"
              size="small"
              type="danger"
              effect="plain"
            >
              AI 短评生成失败
            </el-tag>
            <el-tag v-else size="small" type="info" effect="plain">未附 AI 短评</el-tag>
          </div>
        </template>

        <el-alert
          class="status-alert"
          :title="qualityLabel(s)"
          :description="qualityDescription(s)"
          :type="s.data_quality?.status === 'complete' ? 'info' : 'warning'"
          :closable="false"
          show-icon
        />
        <details v-if="Object.keys(s.data_quality?.field_coverage || {}).length" class="coverage-details">
          <summary>查看策略字段覆盖</summary>
          <ul>
            <li v-for="(coverage, field) in s.data_quality?.field_coverage" :key="field">
              {{ factorLabel(field) }}：{{ coverage.available }} / {{ coverage.total }}
            </li>
          </ul>
        </details>

        <el-empty v-if="s.items.length === 0" :description="strategyEmptyText(s)" :image-size="70" />
        <el-table v-else :data="s.items" stripe size="small">
          <el-table-column prop="symbol" label="代码" width="100">
            <template #default="{ row }">
              <el-link type="primary" @click="viewDetail(row)">{{ row.symbol }}</el-link>
            </template>
          </el-table-column>
          <el-table-column prop="name" label="名称" width="110" />
          <el-table-column prop="industry" label="行业" width="130">
            <template #default="{ row }">{{ row.industry || '-' }}</template>
          </el-table-column>
          <el-table-column prop="score" label="策略得分" width="100" align="right">
            <template #default="{ row }">
              <span v-if="row.score !== null && row.score !== undefined" class="score-value">
                {{ row.score.toFixed(1) }}
              </span>
              <span v-else class="text-gray-400">-</span>
            </template>
          </el-table-column>
          <el-table-column label="入选信号" min-width="220">
            <template #default="{ row }">
              <span class="signals-cell">{{ formatSignals(row.signal_items, row.signals) || '-' }}</span>
            </template>
          </el-table-column>
          <el-table-column label="AI 短评（可选）" min-width="260">
            <template #default="{ row }">
              <span v-if="row.insight" class="insight-cell">{{ row.insight }}</span>
              <span v-else class="text-gray-400">未生成</span>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="130" fixed="right">
            <template #default="{ row }">
              <el-button link size="small" type="primary" @click="analyze(row)">分析</el-button>
              <el-button link size="small" @click="viewDetail(row)">详情</el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-collapse-item>
    </el-collapse>
    </template>
  </div>
</template>

<script setup lang="ts">
// 只读取已落库结果；不在页面加载/刷新时同步数据或触发 AI 调用。
import { ref, computed, onMounted, onBeforeUnmount } from 'vue'
import { useRouter } from 'vue-router'
import { Refresh } from '@element-plus/icons-vue'
import { screeningApi, type DailyResp, type DailyStrategyEntry, type StrategyRunItem } from '@/api/screening'
import { normalizeMarketForAnalysis } from '@/utils/market'
import { useAuthStore } from '@/stores/auth'
import { FACTOR_LABELS, formatSignals } from '@/constants/screening'
import { parseDailyResponse, dailyEmptyNotice, dailyFreshnessNotice, strategyEmptyText } from '@/utils/screeningDaily'

defineOptions({ name: 'ScreeningDailyTab' })

const router = useRouter()
const authStore = useAuthStore()

const loading = ref(false)
const loadError = ref('')
const data = ref<DailyResp | null>(null)
const strategies = computed(() => data.value?.strategies || [])
const emptyNotice = computed(() => dailyEmptyNotice(data.value || { trade_date: null, strategies: [] }))
const freshnessNotice = computed(() => data.value ? dailyFreshnessNotice(data.value) : null)
const activeNames = ref<string[]>([])
let loadSequence = 0

const load = async () => {
  const sequence = ++loadSequence
  loading.value = true
  loadError.value = ''
  // 不让旧列表在刷新失败后看起来像本次成功读取的结果。
  data.value = null
  try {
    const res = await screeningApi.getDaily()
    if (sequence !== loadSequence) return
    data.value = parseDailyResponse(res)
    activeNames.value = activeNames.value.filter(id => strategies.value.some(s => s.strategy_id === id))
    if (strategies.value.length && activeNames.value.length === 0) {
      activeNames.value = [strategies.value[0].strategy_id]
    }
  } catch (error: unknown) {
    if (sequence !== loadSequence) return
    loadError.value = error instanceof Error ? error.message : '请求失败，请检查网络或服务状态后重试。'
  } finally {
    if (sequence === loadSequence) loading.value = false
  }
}

const factorLabel = (field: string): string => {
  const scoreLabels: Record<string, string> = {
    score_short_term: '短线策略得分', score_balanced: '均衡策略得分', score_value: '价值策略得分'
  }
  return FACTOR_LABELS[field] || scoreLabels[field] || field
}

const qualityLabel = (entry: DailyStrategyEntry): string => {
  switch (entry.data_quality?.status) {
    case 'complete': return '策略字段覆盖完整'
    case 'partial': return '策略数据部分缺失'
    case 'insufficient': return '策略数据不足'
    default: return '数据覆盖未知'
  }
}

const qualityTagType = (entry: DailyStrategyEntry): 'success' | 'warning' | 'info' =>
  entry.data_quality?.status === 'complete' ? 'success' :
    !entry.data_quality || entry.data_quality.status === 'unknown' ? 'info' : 'warning'

const qualityDescription = (entry: DailyStrategyEntry): string => {
  const quality = entry.data_quality
  if (!quality || quality.status === 'unknown') return '该推荐未记录字段覆盖信息，不能据此确认输入数据完整。'
  const parts = [`可参与筛选 ${quality.eligible_count} / ${quality.total_universe} 只（非入选数量）。`]
  if (quality.missing_fields?.length) parts.push(`完全缺失：${quality.missing_fields.map(factorLabel).join('、')}。`)
  if (quality.partial_fields?.length) parts.push(`部分覆盖：${quality.partial_fields.map(factorLabel).join('、')}。`)
  if (quality.status === 'complete') parts.push('仅表示本策略所用字段有值，不代表数据时效或投资结论已获验证。')
  else parts.push('筛选结果受缺失字段限制；缺失值不等于零，也不代表不符合策略。')
  return parts.join(' ')
}

const analyze = (row: StrategyRunItem) => {
  router.push({
    name: 'SingleAnalysis',
    query: {
      stock: row.symbol,
      market: normalizeMarketForAnalysis('A股')
    }
  })
}

const viewDetail = (row: StrategyRunItem) => {
  router.push({ name: 'StockDetail', params: { code: row.symbol } })
}

/** 空态时引导去数据中心检查/补同步因子依赖的数据 */
const goDataCenter = () => {
  router.push('/data')
}

const goScheduler = () => {
  router.push({ name: 'SchedulerManagement' })
}

onMounted(load)
onBeforeUnmount(() => { loadSequence++ })
</script>

<style scoped>
.daily-toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
  gap: 12px;
}

.trade-date {
  font-size: 13px;
  color: var(--el-text-color-secondary);
}

.factor-date {
  display: block;
  margin-top: 4px;
}

.status-alert {
  margin-bottom: 12px;
}

.loading-state,
.coverage-details {
  color: var(--el-text-color-secondary);
  font-size: 13px;
  line-height: 1.6;
  margin-bottom: 16px;
}

.coverage-details summary {
  cursor: pointer;
}

.coverage-details ul {
  display: flex;
  flex-wrap: wrap;
  gap: 4px 24px;
  padding-left: 20px;
}

.empty-title {
  margin: 0;
}

.empty-desc {
  margin: 4px 0 0;
  font-size: 13px;
  color: var(--el-text-color-secondary);
  line-height: 1.5;
  max-width: 640px;
}

.collapse-title {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  padding: 10px 0;
  line-height: 1.5;
}

.daily-tab :deep(.el-collapse-item__header) {
  height: auto;
  min-height: 48px;
}

.collapse-title .name {
  font-weight: 600;
}

.score-value {
  font-weight: 600;
  color: var(--el-color-primary);
}

.signals-cell,
.insight-cell {
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
  font-size: 13px;
  line-height: 1.5;
}
</style>
