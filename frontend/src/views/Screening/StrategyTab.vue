<template>
  <div class="strategy-tab">
    <!-- 策略选择 -->
    <el-card shadow="never" class="strategy-panel">
      <template #header>
        <div class="card-header">
          <span>策略模板</span>
          <span v-if="asOf" class="as-of">数据截至 {{ asOf }}</span>
        </div>
      </template>

      <div v-loading="strategiesLoading">
        <div v-if="strategies.length === 0 && !strategiesLoading" class="empty-hint">
          暂无策略模板
        </div>
        <div class="strategy-cards">
          <el-card
            v-for="s in strategies"
            :key="s.id"
            shadow="hover"
            class="strategy-card"
            :class="{ active: selectedStrategyId === s.id }"
            @click="selectStrategy(s.id)"
          >
            <div class="strategy-card-title">
              <span>{{ s.name }}</span>
              <el-tag v-if="s.is_default" type="primary" size="small">默认</el-tag>
              <el-tag :type="styleTagType(s.style)" size="small" effect="plain">
                {{ styleLabel(s.style) }}
              </el-tag>
            </div>
            <p class="strategy-card-desc">{{ s.description }}</p>
          </el-card>
        </div>
      </div>
    </el-card>

    <!-- 策略结果 -->
    <el-card shadow="never" class="results-panel">
      <template #header>
        <div class="card-header">
          <span>策略结果（{{ items.length }} 只）</span>
          <div class="header-actions">
            <el-button type="primary" :loading="runLoading" @click="runSelected">
              <el-icon><Search /></el-icon>
              重新运行
            </el-button>
            <el-button
              type="warning"
              :disabled="selectedRows.length === 0 || insightLoading"
              :loading="insightLoading"
              @click="confirmInsight"
            >
              <el-icon><MagicStick /></el-icon>
              AI 快速研判{{ quotaRemaining !== null ? `（今日剩余 ${quotaRemaining} 次）` : '' }}
            </el-button>
          </div>
        </div>
      </template>

      <el-alert
        v-if="quotaRemaining !== null && quotaRemaining <= 0"
        type="warning"
        :closable="false"
        show-icon
        title="今日 AI 研判配额已用完，明日恢复或联系管理员调整配额"
        class="quota-alert"
      />

      <!-- 运行后空结果：展示策略自身的数据依赖说明，并引导去数据中心补数 -->
      <el-empty
        v-if="hasRun && !runLoading && items.length === 0"
        :image-size="160"
      >
        <template #description>
          <p class="empty-title">该策略今日无入选股票（因子数据可能尚未批算）</p>
          <p v-if="currentStrategy?.description" class="empty-desc">
            策略依赖：{{ currentStrategy.description }}
          </p>
        </template>
        <el-button type="primary" @click="goDataCenter">前往数据中心</el-button>
      </el-empty>

      <el-table
        v-else
        :data="items"
        v-loading="runLoading"
        stripe
        @selection-change="onSelectionChange"
      >
        <el-table-column type="selection" width="55" />
        <el-table-column type="expand">
          <template #default="{ row }">
            <div class="expand-content">
              <div class="expand-factors">
                <el-tag
                  v-for="(v, k) in row.factors"
                  :key="k"
                  type="info"
                  effect="plain"
                  class="factor-tag"
                >
                  {{ factorLabel(String(k)) }}: {{ formatFactor(v) }}
                </el-tag>
              </div>
              <div v-if="row.signals.length || row.signal_items?.length" class="expand-signals">
                入选信号：{{ formatSignals(row.signal_items, row.signals) }}
              </div>
              <div v-if="insights[row.symbol]" class="expand-insight">
                <el-icon><MagicStick /></el-icon>
                {{ insights[row.symbol] }}
              </div>
            </div>
          </template>
        </el-table-column>

        <el-table-column prop="symbol" label="代码" width="100">
          <template #default="{ row }">
            <el-link type="primary" @click="viewDetail(row)">{{ row.symbol }}</el-link>
          </template>
        </el-table-column>
        <el-table-column prop="name" label="名称" width="110" />
        <el-table-column prop="industry" label="行业" width="120">
          <template #default="{ row }">{{ row.industry || '-' }}</template>
        </el-table-column>
        <el-table-column prop="score" label="策略得分" width="110" align="right">
          <template #default="{ row }">
            <span v-if="row.score !== null && row.score !== undefined" class="score-value">
              {{ row.score.toFixed(1) }}
            </span>
            <span v-else class="text-gray-400">-</span>
          </template>
        </el-table-column>
        <el-table-column label="AI 研判" min-width="200">
          <template #default="{ row }">
            <span v-if="insights[row.symbol]" class="insight-cell">{{ insights[row.symbol] }}</span>
            <span v-else class="text-gray-400">未生成</span>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="140" fixed="right">
          <template #default="{ row }">
            <el-button link size="small" type="primary" @click="analyze(row)">分析</el-button>
            <el-button link size="small" @click="viewDetail(row)">详情</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>
  </div>
</template>

<script setup lang="ts">
// 策略选股 Tab：L0 因子策略运行 + L1 手动 AI 研判入口
// （研判消耗 token，须用户确认后调用，剩余额度实时展示）
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Search, MagicStick } from '@element-plus/icons-vue'
import {
  screeningApi,
  type StrategyInfo,
  type StrategyRunItem
} from '@/api/screening'
import { normalizeMarketForAnalysis } from '@/utils/market'
import { FACTOR_LABELS, formatSignals } from '@/constants/screening'

defineOptions({ name: 'ScreeningStrategyTab' })

const router = useRouter()

const strategies = ref<StrategyInfo[]>([])
const strategiesLoading = ref(false)
const selectedStrategyId = ref<string>('')
const items = ref<StrategyRunItem[]>([])
const asOf = ref<string | null>(null)
const runLoading = ref(false)
const selectedRows = ref<StrategyRunItem[]>([])
// 是否已完成过一次运行（区分「未运行」与「运行后空结果」两种空表展示）
const hasRun = ref(false)

// L1 研判
const quotaRemaining = ref<number | null>(null)
const insightLoading = ref(false)
const insights = ref<Record<string, string>>({})

const STYLE_LABELS: Record<string, string> = {
  short_term: '短线',
  balanced: '均衡',
  value: '价值'
}

// 当前选中策略（空结果时展示其 description 中的数据依赖说明）
const currentStrategy = computed(() =>
  strategies.value.find(s => s.id === selectedStrategyId.value)
)

const styleLabel = (s: string) => STYLE_LABELS[s] || s
const styleTagType = (s: string) =>
  s === 'short_term' ? 'danger' : s === 'value' ? 'success' : 'warning'
const factorLabel = (k: string) => FACTOR_LABELS[k] || k
const formatFactor = (v: number) =>
  typeof v === 'number' ? v.toFixed(2) : String(v)

const selectStrategy = (id: string) => {
  if (selectedStrategyId.value === id) return
  selectedStrategyId.value = id
  runSelected()
}

const runSelected = async () => {
  if (!selectedStrategyId.value) return
  runLoading.value = true
  try {
    const res = await screeningApi.runStrategy(selectedStrategyId.value)
    const data = (res as any)?.data || res
    items.value = data?.items || []
    asOf.value = data?.as_of || null
    hasRun.value = true
  } catch (e: any) {
    ElMessage.error(e?.message || '策略运行失败')
  } finally {
    runLoading.value = false
  }
}

const onSelectionChange = (rows: StrategyRunItem[]) => {
  selectedRows.value = rows
}

/** AI 研判确认框：明确告知消耗 token，用户确认后才调用 */
const confirmInsight = async () => {
  if (selectedRows.value.length === 0) return
  if (quotaRemaining.value !== null && quotaRemaining.value <= 0) {
    ElMessage.warning('今日 AI 研判配额已用完')
    return
  }
  try {
    await ElMessageBox.confirm(
      `将对选中的 ${selectedRows.value.length} 只股票调用 AI 生成快速研判，` +
        '会消耗 LLM token（计入今日配额），确定继续吗？',
      'AI 快速研判',
      {
        confirmButtonText: '开始研判',
        cancelButtonText: '取消',
        type: 'warning'
      }
    )
  } catch {
    return // 用户取消
  }

  insightLoading.value = true
  try {
    const symbols = selectedRows.value.map(r => r.symbol).slice(0, 30)
    const res = await screeningApi.postInsights(
      symbols, selectedStrategyId.value)
    const data = (res as any)?.data || res
    if (data?.insights) {
      insights.value = { ...insights.value, ...data.insights }
    }
    if (data?.quota_remaining !== undefined) {
      quotaRemaining.value = data.quota_remaining
    }
    ElMessage.success('AI 研判完成，可在列表「AI 研判」列查看')
  } catch (e: any) {
    ElMessage.error(e?.message || 'AI 研判失败（失败不扣配额）')
  } finally {
    insightLoading.value = false
  }
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

/** 空结果时引导去数据中心补同步因子依赖的基础数据 */
const goDataCenter = () => {
  router.push('/data')
}

const refreshQuota = async () => {
  try {
    const res = await screeningApi.getInsightQuota()
    const data = (res as any)?.data || res
    quotaRemaining.value = data?.quota_remaining ?? null
  } catch {
    quotaRemaining.value = null
  }
}

onMounted(async () => {
  refreshQuota()
  strategiesLoading.value = true
  try {
    const res = await screeningApi.getStrategies()
    const data = (res as any)?.data || res
    strategies.value = data?.strategies || []
    const def = strategies.value.find(s => s.is_default) || strategies.value[0]
    if (def) {
      selectedStrategyId.value = def.id
      await runSelected()
    }
  } catch (e: any) {
    ElMessage.error(e?.message || '获取策略列表失败')
  } finally {
    strategiesLoading.value = false
  }
})
</script>

<style scoped>
.strategy-panel {
  margin-bottom: 16px;
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.as-of {
  font-size: 13px;
  color: var(--el-text-color-secondary);
}

.header-actions {
  display: flex;
  gap: 8px;
}

.strategy-cards {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(240px, 1fr));
  gap: 12px;
}

.strategy-card {
  cursor: pointer;
  border: 1px solid var(--el-border-color-light);
  transition: border-color 0.2s;
}

.strategy-card.active {
  border-color: var(--el-color-primary);
}

.strategy-card-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-weight: 600;
}

.strategy-card-desc {
  margin: 8px 0 0;
  font-size: 13px;
  color: var(--el-text-color-secondary);
  line-height: 1.5;
}

.empty-hint {
  text-align: center;
  color: var(--el-text-color-secondary);
  padding: 16px 0;
}

.empty-title {
  margin: 0;
}

.empty-desc {
  margin: 4px 0 0;
  font-size: 13px;
  color: var(--el-text-color-secondary);
  line-height: 1.5;
}

.quota-alert {
  margin-bottom: 12px;
}

.score-value {
  font-weight: 600;
  color: var(--el-color-primary);
}

.insight-cell {
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
  font-size: 13px;
  line-height: 1.5;
}

.expand-content {
  padding: 8px 16px;
}

.expand-factors {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.factor-tag {
  font-size: 12px;
}

.expand-signals {
  margin-top: 8px;
  font-size: 13px;
  color: var(--el-text-color-secondary);
}

.expand-insight {
  margin-top: 8px;
  padding: 10px 12px;
  background: var(--el-fill-color-light);
  border-radius: 6px;
  font-size: 13px;
  line-height: 1.6;
}

.expand-insight .el-icon {
  vertical-align: middle;
  margin-right: 6px;
  color: var(--el-color-warning);
}
</style>
