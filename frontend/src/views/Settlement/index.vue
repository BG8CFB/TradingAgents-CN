<template>
  <div class="settlement-page">
    <!-- 页头 -->
    <div class="page-header">
      <div class="page-header-left">
        <h1 class="page-title">
          <el-icon><Trophy /></el-icon>
          结算记分卡
        </h1>
        <p class="page-description">AI 决策到期自动结算的成绩单</p>
      </div>
      <div class="page-header-right">
        <el-radio-group v-model="channel" size="small" @change="onChannelChange">
          <el-radio-button value="online">在线</el-radio-button>
          <el-radio-button value="backtest">回测</el-radio-button>
          <el-radio-button value="all">全部</el-radio-button>
        </el-radio-group>
        <span class="update-hint">60秒自动刷新{{ lastRefreshTime ? ` · 上次刷新 ${lastRefreshTime}` : '' }}</span>
        <el-button size="small" plain type="primary" :loading="refreshing" @click="handleRefresh">
          <el-icon><Refresh /></el-icon>
          刷新
        </el-button>
      </div>
    </div>

    <el-card class="tabs-card" shadow="never">
      <el-tabs v-model="activeTab">
        <!-- Tab 1: 记分卡 -->
        <el-tab-pane label="记分卡" name="scorecard">
          <div v-loading="scoreLoading" class="scorecard-body">
            <el-row :gutter="12">
              <el-col v-for="card in statCards" :key="card.label" :xs="12" :sm="6">
                <el-card shadow="never" class="stat-card">
                  <div class="stat">
                    <div class="stat-value">{{ card.value }}</div>
                    <div class="stat-label">{{ card.label }}</div>
                    <div class="stat-sub">{{ card.sub }}</div>
                  </div>
                </el-card>
              </el-col>
            </el-row>

            <el-row :gutter="12" class="section-row">
              <el-col :xs="24" :sm="12">
                <el-card shadow="never">
                  <div class="hit-rate">
                    <div class="hit-rate-value" :class="{ empty: scorecard?.hit_rate == null }">
                      {{ hitRateText }}
                    </div>
                    <div class="hit-rate-label">方向命中率（已结算非 Hold 决策）</div>
                    <div v-if="scorecard?.hit_rate != null" class="hit-rate-meta">
                      <span>95% CI {{ ciText }}</span>
                      <span>样本 {{ scorecard.settled_count }} 条</span>
                      <span>平均收益 {{ returnText(scorecard.avg_return_pct) }}</span>
                      <span>收益中位数 {{ returnText(scorecard.median_return_pct) }}</span>
                    </div>
                    <div v-if="scorecard?.alpha_count" class="hit-rate-meta">
                      <span>平均超额 {{ returnText(scorecard.avg_alpha_pct) }}</span>
                      <span>超额中位数 {{ returnText(scorecard.median_alpha_pct) }}</span>
                      <span>跑赢基准 {{ pctText(scorecard.benchmark_hit_rate) }}（alpha 样本 {{ scorecard.alpha_count }} 条）</span>
                    </div>
                  </div>
                </el-card>
              </el-col>
            </el-row>

            <el-row :gutter="12" class="section-row">
              <el-col :xs="24" :lg="12">
                <el-card shadow="never">
                  <template #header><span class="card-title">置信度校准</span></template>
                  <v-chart class="chart" :option="calibrationOption" autoresize />
                </el-card>
              </el-col>
              <el-col :xs="24" :lg="12">
                <el-card shadow="never">
                  <template #header><span class="card-title">命中率趋势（95% 置信区间）</span></template>
                  <v-chart class="chart" :option="trendOption" autoresize />
                </el-card>
              </el-col>
            </el-row>

            <el-card shadow="never" class="section-row">
              <template #header><span class="card-title">分信号统计</span></template>
              <el-table :data="scorecard?.by_signal ?? []" size="small">
                <el-table-column label="信号" width="120">
                  <template #default="{ row }">{{ signalLabel(row.signal) }}</template>
                </el-table-column>
                <el-table-column prop="count" label="样本" width="120" />
                <el-table-column label="命中率">
                  <template #default="{ row }">{{ pctText(row.hit_rate) }}</template>
                </el-table-column>
                <el-table-column label="平均收益">
                  <template #default="{ row }">{{ returnText(row.avg_return_pct) }}</template>
                </el-table-column>
                <el-table-column label="平均超额">
                  <template #default="{ row }">{{ returnText(row.avg_alpha_pct) }}</template>
                </el-table-column>
              </el-table>
            </el-card>

            <el-card shadow="never" class="section-row">
              <template #header><span class="card-title">分期限统计</span></template>
              <el-table :data="scorecard?.by_horizon ?? []" size="small">
                <el-table-column label="持有期" width="140">
                  <template #default="{ row }">{{ horizonDaysLabel(row.horizon_days) }}</template>
                </el-table-column>
                <el-table-column prop="count" label="样本" width="120" />
                <el-table-column prop="pending" label="待到期" width="120" />
                <el-table-column label="命中率（已结算）">
                  <template #default="{ row }">{{ pctText(row.hit_rate) }}</template>
                </el-table-column>
                <el-table-column label="平均收益">
                  <template #default="{ row }">{{ returnText(row.avg_return_pct) }}</template>
                </el-table-column>
              </el-table>
              <div class="horizon-note">待到期决策只计数不阅卷，避免长线判断被短窗口误伤</div>
            </el-card>
          </div>
        </el-tab-pane>

        <!-- Tab 2: 结算记录 -->
        <el-tab-pane label="结算记录" name="records">
          <el-form :inline="true" @submit.prevent>
            <el-form-item label="标的">
              <el-input v-model="recFilters.symbol" placeholder="代码" clearable style="width: 140px" />
            </el-form-item>
            <el-form-item label="状态">
              <el-select v-model="recFilters.status" clearable placeholder="全部" style="width: 110px">
                <el-option label="全部" value="" />
                <el-option label="待结算" value="pending" />
                <el-option label="已结算" value="settled" />
                <el-option label="无法成交" value="unfillable" />
              </el-select>
            </el-form-item>
            <el-form-item label="信号">
              <el-select v-model="recFilters.signal" clearable placeholder="全部" style="width: 100px">
                <el-option label="全部" value="" />
                <el-option label="买入" value="Buy" />
                <el-option label="持有" value="Hold" />
                <el-option label="卖出" value="Sell" />
              </el-select>
            </el-form-item>
            <el-form-item label="持有期">
              <el-select v-model="recFilters.horizonDays" clearable placeholder="全部" style="width: 110px">
                <el-option label="全部" value="" />
                <el-option v-for="opt in HORIZON_FILTERS" :key="opt.value" :label="opt.label" :value="opt.value" />
              </el-select>
            </el-form-item>
            <el-form-item label="错题类型">
              <el-select v-model="recFilters.errorType" clearable placeholder="全部" style="width: 110px">
                <el-option label="全部" value="" />
                <el-option label="方向错" value="direction_wrong" />
                <el-option label="不可执行" value="unfillable" />
              </el-select>
            </el-form-item>
            <el-form-item label="决策日期">
              <el-date-picker
                v-model="recFilters.dateRange"
                type="daterange"
                range-separator="至"
                start-placeholder="开始日期"
                end-placeholder="结束日期"
                format="YYYY-MM-DD"
                value-format="YYYY-MM-DD"
                style="width: 260px"
              />
            </el-form-item>
            <el-form-item>
              <el-button type="primary" :loading="recLoading" @click="applyRecFilters">查询</el-button>
              <el-button @click="resetRecFilters">重置</el-button>
            </el-form-item>
          </el-form>

          <el-table
            v-loading="recLoading"
            :data="recItems"
            size="small"
            style="width: 100%"
            class="hidden-sm-and-down"
          >
            <el-table-column label="标的" min-width="140">
              <template #default="{ row }">
                <span class="symbol-text">{{ row.symbol }}</span>
                <span v-if="row.stock_name" class="name-text">{{ row.stock_name }}</span>
              </template>
            </el-table-column>
            <el-table-column label="信号" width="80">
              <template #default="{ row }">
                <el-tag :type="signalTagType(row.signal)" size="small">{{ signalLabel(row.signal) }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="置信度" width="80" align="right">
              <template #default="{ row }">{{ confidenceText(row.stated_confidence) }}</template>
            </el-table-column>
            <el-table-column label="决策日" width="110">
              <template #default="{ row }">{{ dateText(row.decision_date) }}</template>
            </el-table-column>
            <el-table-column label="持有期" width="96">
              <template #default="{ row }">{{ horizonDaysLabel(row.horizon_days) }}</template>
            </el-table-column>
            <el-table-column label="状态" width="96">
              <template #default="{ row }">
                <el-tag :type="statusTagType(row.status)" size="small">{{ statusLabel(row.status) }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="入场价" width="90" align="right">
              <template #default="{ row }">{{ numText(row.entry_price) }}</template>
            </el-table-column>
            <el-table-column label="出场价" width="90" align="right">
              <template #default="{ row }">{{ numText(row.exit_price) }}</template>
            </el-table-column>
            <el-table-column label="收益%" width="90" align="right">
              <template #default="{ row }">
                <span :class="returnClass(row.return_pct)">{{ returnText(row.return_pct) }}</span>
              </template>
            </el-table-column>
            <el-table-column label="超额%" width="90" align="right">
              <template #default="{ row }">
                <span :class="returnClass(row.alpha_pct)">{{ returnText(row.alpha_pct) }}</span>
              </template>
            </el-table-column>
            <el-table-column label="方向" width="70" align="center">
              <template #default="{ row }">
                <el-tag v-if="row.direction_hit === true" type="success" size="small">对</el-tag>
                <el-tag v-else-if="row.direction_hit === false" type="danger" size="small">错</el-tag>
                <span v-else>—</span>
              </template>
            </el-table-column>
            <el-table-column label="错题类型" width="96">
              <template #default="{ row }">{{ errorTypeLabel(row.error_type) }}</template>
            </el-table-column>
            <el-table-column label="失败原因" min-width="160" show-overflow-tooltip>
              <template #default="{ row }">{{ row.failure_reason || '—' }}</template>
            </el-table-column>
          </el-table>

          <MobileTable
            class="hidden-md-and-up"
            :rows="recItems"
            :columns="recMobileColumns"
            row-key="task_id"
            head-prop="symbol"
            head-right-prop="return_pct"
          >
            <template #head="{ row }">
              {{ row.symbol }}<span v-if="row.stock_name"> {{ row.stock_name }}</span>
            </template>
            <template #headRight="{ row }">
              <span :class="returnClass(row.return_pct)">{{ returnText(row.return_pct) }}</span>
            </template>
            <template #signal="{ row }">
              <el-tag :type="signalTagType(row.signal)" size="small">{{ signalLabel(row.signal) }}</el-tag>
            </template>
            <template #status="{ row }">
              <el-tag :type="statusTagType(row.status)" size="small">{{ statusLabel(row.status) }}</el-tag>
            </template>
          </MobileTable>

          <div class="pagination-wrapper">
            <el-pagination
              v-model:current-page="recPage"
              v-model:page-size="recPageSize"
              :page-sizes="[20, 50, 100]"
              :total="recTotal"
              layout="total, sizes, prev, pager, next, jumper"
              @size-change="onRecSizeChange"
              @current-change="onRecPageChange"
            />
          </div>
        </el-tab-pane>

        <!-- Tab 3: 错题本 -->
        <el-tab-pane label="错题本" name="errors">
          <p class="error-desc">错题由结算规则自动派生：方向错=信号与实际涨跌相反；不可执行=一字板无法成交</p>

          <div class="error-chip-row">
            <button
              v-for="t in ERROR_TYPES"
              :key="t"
              type="button"
              class="error-chip"
              :class="{ active: errType === t }"
              @click="switchErrType(t)"
            >
              <span class="chip-count">{{ errCounts[t] }}</span>
              <span class="chip-label">{{ ERROR_TYPE_LABELS[t] }}</span>
            </button>
          </div>

          <el-form :inline="true" @submit.prevent>
            <el-form-item label="标的">
              <el-input v-model="errFilters.symbol" placeholder="代码" clearable style="width: 140px" />
            </el-form-item>
            <el-form-item label="决策日期">
              <el-date-picker
                v-model="errFilters.dateRange"
                type="daterange"
                range-separator="至"
                start-placeholder="开始日期"
                end-placeholder="结束日期"
                format="YYYY-MM-DD"
                value-format="YYYY-MM-DD"
                style="width: 260px"
              />
            </el-form-item>
            <el-form-item>
              <el-button type="primary" :loading="errLoading" @click="applyErrFilters">查询</el-button>
              <el-button @click="resetErrFilters">重置</el-button>
            </el-form-item>
          </el-form>

          <el-table
            v-loading="errLoading"
            :data="errItems"
            size="small"
            style="width: 100%"
            class="hidden-sm-and-down"
          >
            <el-table-column label="标的" min-width="140">
              <template #default="{ row }">
                <span class="symbol-text">{{ row.symbol }}</span>
                <span v-if="row.stock_name" class="name-text">{{ row.stock_name }}</span>
              </template>
            </el-table-column>
            <el-table-column label="信号" width="80">
              <template #default="{ row }">
                <el-tag :type="signalTagType(row.signal)" size="small">{{ signalLabel(row.signal) }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="置信度" width="80" align="right">
              <template #default="{ row }">{{ confidenceText(row.stated_confidence) }}</template>
            </el-table-column>
            <el-table-column label="决策日" width="110">
              <template #default="{ row }">{{ dateText(row.decision_date) }}</template>
            </el-table-column>
            <el-table-column label="状态" width="96">
              <template #default="{ row }">
                <el-tag :type="statusTagType(row.status)" size="small">{{ statusLabel(row.status) }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="入场价" width="90" align="right">
              <template #default="{ row }">{{ numText(row.entry_price) }}</template>
            </el-table-column>
            <el-table-column label="出场价" width="90" align="right">
              <template #default="{ row }">{{ numText(row.exit_price) }}</template>
            </el-table-column>
            <el-table-column label="收益%" width="90" align="right">
              <template #default="{ row }">
                <span :class="returnClass(row.return_pct)">{{ returnText(row.return_pct) }}</span>
              </template>
            </el-table-column>
            <el-table-column label="超额%" width="90" align="right">
              <template #default="{ row }">
                <span :class="returnClass(row.alpha_pct)">{{ returnText(row.alpha_pct) }}</span>
              </template>
            </el-table-column>
            <el-table-column label="方向" width="70" align="center">
              <template #default="{ row }">
                <el-tag v-if="row.direction_hit === true" type="success" size="small">对</el-tag>
                <el-tag v-else-if="row.direction_hit === false" type="danger" size="small">错</el-tag>
                <span v-else>—</span>
              </template>
            </el-table-column>
            <el-table-column label="错题类型" width="96">
              <template #default="{ row }">{{ errorTypeLabel(row.error_type) }}</template>
            </el-table-column>
            <el-table-column label="失败原因" min-width="160" show-overflow-tooltip>
              <template #default="{ row }">{{ row.failure_reason || '—' }}</template>
            </el-table-column>
          </el-table>

          <MobileTable
            class="hidden-md-and-up"
            :rows="errItems"
            :columns="recMobileColumns"
            row-key="task_id"
            head-prop="symbol"
            head-right-prop="return_pct"
          >
            <template #head="{ row }">
              {{ row.symbol }}<span v-if="row.stock_name"> {{ row.stock_name }}</span>
            </template>
            <template #headRight="{ row }">
              <span :class="returnClass(row.return_pct)">{{ returnText(row.return_pct) }}</span>
            </template>
            <template #signal="{ row }">
              <el-tag :type="signalTagType(row.signal)" size="small">{{ signalLabel(row.signal) }}</el-tag>
            </template>
            <template #status="{ row }">
              <el-tag :type="statusTagType(row.status)" size="small">{{ statusLabel(row.status) }}</el-tag>
            </template>
          </MobileTable>

          <div class="pagination-wrapper">
            <el-pagination
              v-model:current-page="errPage"
              v-model:page-size="errPageSize"
              :page-sizes="[20, 50, 100]"
              :total="errTotal"
              layout="total, sizes, prev, pager, next, jumper"
              @size-change="onErrSizeChange"
              @current-change="onErrPageChange"
            />
          </div>
        </el-tab-pane>
      </el-tabs>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { Trophy, Refresh } from '@element-plus/icons-vue'
import { use as echartsUse } from 'echarts/core'
import { LineChart, ScatterChart } from 'echarts/charts'
import {
  GridComponent,
  TooltipComponent,
  TitleComponent,
  MarkLineComponent
} from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import VChart from 'vue-echarts'
import type { EChartsOption } from 'echarts'
import MobileTable from '@/components/Global/MobileTable.vue'
import { usePolling } from '@/composables/usePolling'
import { formatDate } from '@/utils/datetime'
import {
  getSettlementRecords,
  getSettlementScorecard,
  type Scorecard,
  type SettlementRecord
} from '@/api/settlement'

echartsUse([
  LineChart,
  ScatterChart,
  GridComponent,
  TooltipComponent,
  TitleComponent,
  MarkLineComponent,
  CanvasRenderer
])

type Channel = 'online' | 'backtest' | 'all'
type ErrType = 'direction_wrong' | 'unfillable'

const ERROR_TYPES: ErrType[] = ['direction_wrong', 'unfillable']
const ERROR_TYPE_LABELS: Record<ErrType, string> = {
  direction_wrong: '方向错',
  unfillable: '不可执行'
}

const channel = ref<Channel>('online')
const activeTab = ref<'scorecard' | 'records' | 'errors'>('scorecard')
const refreshing = ref(false)

// ── 记分卡 ────────────────────────────────────────────
const scorecard = ref<Scorecard | null>(null)
const scoreLoading = ref(false)

async function loadScorecard() {
  scoreLoading.value = true
  try {
    const res = await getSettlementScorecard({ channel: channel.value, months: 12 })
    scorecard.value = res.data ?? null
  } catch (e: unknown) {
    ElMessage.error((e as Error)?.message || '记分卡加载失败')
  } finally {
    scoreLoading.value = false
  }
}

const statCards = computed(() => {
  const s = scorecard.value
  return [
    { label: '已登记', value: s?.total_registered ?? 0, sub: `Hold ${s?.hold_count ?? 0} 条` },
    { label: '已结算', value: s?.settled_count ?? 0, sub: ratioText(s?.settled_count, s?.total_registered) },
    { label: '待结算', value: s?.pending_count ?? 0, sub: ratioText(s?.pending_count, s?.total_registered) },
    { label: '无法成交', value: s?.unfillable_count ?? 0, sub: ratioText(s?.unfillable_count, s?.total_registered) }
  ]
})

const hitRateText = computed(() =>
  scorecard.value?.hit_rate == null ? '暂无样本' : `${(scorecard.value.hit_rate * 100).toFixed(1)}%`
)

const ciText = computed(() => {
  const ci = scorecard.value?.hit_ci
  if (!ci) return '[—, —]'
  return `[${(ci.low * 100).toFixed(1)}%, ${(ci.high * 100).toFixed(1)}%]`
})

// ── 结算记录 ──────────────────────────────────────────
interface RecordFilters {
  symbol: string
  status: string
  signal: string
  errorType: string
  horizonDays: string
  dateRange: string[]
}

const recFilters = ref<RecordFilters>({ symbol: '', status: '', signal: '', errorType: '', horizonDays: '', dateRange: [] })
const recItems = ref<SettlementRecord[]>([])
const recTotal = ref(0)
const recPage = ref(1)
const recPageSize = ref(20)
const recLoading = ref(false)

function buildDateParams(range: string[]): { start_date?: string; end_date?: string } {
  if (range && range.length === 2 && range[0] && range[1]) {
    return { start_date: range[0], end_date: range[1] }
  }
  return {}
}

async function loadRecords() {
  recLoading.value = true
  try {
    const res = await getSettlementRecords({
      page: recPage.value,
      page_size: recPageSize.value,
      symbol: recFilters.value.symbol || undefined,
      status: recFilters.value.status || undefined,
      signal: recFilters.value.signal || undefined,
      error_type: recFilters.value.errorType || undefined,
      horizon_days: recFilters.value.horizonDays ? Number(recFilters.value.horizonDays) : undefined,
      channel: channel.value,
      ...buildDateParams(recFilters.value.dateRange)
    })
    const body = res.data
    recItems.value = body?.items ?? []
    recTotal.value = body?.total ?? 0
  } catch (e: unknown) {
    ElMessage.error((e as Error)?.message || '结算记录加载失败')
  } finally {
    recLoading.value = false
  }
}

function applyRecFilters() {
  recPage.value = 1
  void loadRecords()
}

function resetRecFilters() {
  recFilters.value = { symbol: '', status: '', signal: '', errorType: '', horizonDays: '', dateRange: [] }
  recPage.value = 1
  void loadRecords()
}

function onRecSizeChange(size: number) {
  recPageSize.value = size
  recPage.value = 1
  void loadRecords()
}

function onRecPageChange(page: number) {
  recPage.value = page
  void loadRecords()
}

// ── 错题本 ────────────────────────────────────────────
const errFilters = ref<{ symbol: string; dateRange: string[] }>({ symbol: '', dateRange: [] })
const errType = ref<ErrType>('direction_wrong')
const errItems = ref<SettlementRecord[]>([])
const errTotal = ref(0)
const errPage = ref(1)
const errPageSize = ref(20)
const errLoading = ref(false)
const errCounts = ref<Record<ErrType, number>>({ direction_wrong: 0, unfillable: 0 })

/** 各错题类型计数（total 口径，随共享筛选变化） */
async function loadErrorCounts() {
  const shared = {
    page: 1,
    page_size: 1,
    symbol: errFilters.value.symbol || undefined,
    channel: channel.value,
    ...buildDateParams(errFilters.value.dateRange)
  }
  try {
    const [dw, un] = await Promise.all([
      getSettlementRecords({ ...shared, error_type: 'direction_wrong' }),
      getSettlementRecords({ ...shared, error_type: 'unfillable' })
    ])
    errCounts.value = {
      direction_wrong: dw.data?.total ?? 0,
      unfillable: un.data?.total ?? 0
    }
  } catch (e: unknown) {
    ElMessage.error((e as Error)?.message || '错题统计加载失败')
  }
}

async function loadErrors() {
  errLoading.value = true
  try {
    const res = await getSettlementRecords({
      page: errPage.value,
      page_size: errPageSize.value,
      symbol: errFilters.value.symbol || undefined,
      error_type: errType.value,
      channel: channel.value,
      ...buildDateParams(errFilters.value.dateRange)
    })
    errItems.value = res.data?.items ?? []
    errTotal.value = res.data?.total ?? 0
  } catch (e: unknown) {
    ElMessage.error((e as Error)?.message || '错题记录加载失败')
  } finally {
    errLoading.value = false
  }
}

function switchErrType(t: ErrType) {
  if (errType.value === t) return
  errType.value = t
  errPage.value = 1
  void loadErrors()
}

function applyErrFilters() {
  errPage.value = 1
  void Promise.all([loadErrors(), loadErrorCounts()])
}

function resetErrFilters() {
  errFilters.value = { symbol: '', dateRange: [] }
  errPage.value = 1
  void Promise.all([loadErrors(), loadErrorCounts()])
}

function onErrSizeChange(size: number) {
  errPageSize.value = size
  errPage.value = 1
  void loadErrors()
}

function onErrPageChange(page: number) {
  errPage.value = page
  void loadErrors()
}

// ── 汇总加载 / 轮询 ──────────────────────────────────
async function loadAll() {
  await Promise.all([loadScorecard(), loadRecords(), loadErrors(), loadErrorCounts()])
}

const { lastRefreshTime, refreshNow } = usePolling(loadAll, 60000)

async function handleRefresh() {
  refreshing.value = true
  try {
    await refreshNow()
  } finally {
    refreshing.value = false
  }
}

function onChannelChange() {
  recPage.value = 1
  errPage.value = 1
  void loadAll()
}

onMounted(loadAll)

// ── 展示格式化 ────────────────────────────────────────
const SIGNAL_LABELS: Record<string, string> = { Buy: '买入', Sell: '卖出', Hold: '持有' }
const SIGNAL_TAGS: Record<string, 'success' | 'warning' | 'danger' | 'info'> = {
  Buy: 'success',
  Sell: 'danger',
  Hold: 'warning'
}
const STATUS_LABELS: Record<string, string> = { pending: '待结算', settled: '已结算', unfillable: '无法成交' }

// 持有期档位（与后端 app/core/horizons.py 的 HORIZON_DAYS 对齐；旧记录 horizon_days=7 落短线桶）
const HORIZON_FILTERS = [
  { value: '7', label: '短线 · 7日' },
  { value: '20', label: '中线 · 20日' },
  { value: '60', label: '长线 · 60日' }
]

function horizonDaysLabel(days: number | null | undefined): string {
  if (days === null || days === undefined) return '—'
  return HORIZON_FILTERS.find((o) => Number(o.value) === days)?.label ?? `${days}日`
}
const STATUS_TAGS: Record<string, 'success' | 'warning' | 'info'> = {
  pending: 'warning',
  settled: 'success',
  unfillable: 'info'
}

function signalLabel(s: string): string {
  return SIGNAL_LABELS[s] ?? s
}

function signalTagType(s: string): 'success' | 'warning' | 'danger' | 'info' {
  return SIGNAL_TAGS[s] ?? 'info'
}

function statusLabel(s: string): string {
  return STATUS_LABELS[s] ?? s
}

function statusTagType(s: string): 'success' | 'warning' | 'info' {
  return STATUS_TAGS[s] ?? 'info'
}

function errorTypeLabel(t: string | null): string {
  return t ? (ERROR_TYPE_LABELS as Record<string, string>)[t] ?? t : '—'
}

function pctText(v: number | null | undefined, digits = 1): string {
  return v === null || v === undefined ? '—' : `${(v * 100).toFixed(digits)}%`
}

function ratioText(count: number | undefined, total: number | undefined): string {
  if (!total) return '—'
  return `占比 ${(((count ?? 0) / total) * 100).toFixed(1)}%`
}

function returnText(v: number | null | undefined): string {
  if (v === null || v === undefined) return '—'
  return `${v > 0 ? '+' : ''}${v.toFixed(2)}%`
}

/** A 股口径红涨绿跌 */
function returnClass(v: number | null | undefined): string {
  if (v === null || v === undefined || v === 0) return ''
  return v > 0 ? 'up' : 'down'
}

function numText(v: number | null | undefined): string {
  return v === null || v === undefined ? '—' : v.toFixed(2)
}

function confidenceText(v: number | null | undefined): string {
  return v === null || v === undefined ? '—' : `${Math.round(v)}%`
}

function dateText(d: string | null): string {
  return d ? formatDate(d) : '—'
}

// ── 移动端卡片列 ──────────────────────────────────────
interface MobileCol {
  prop: string
  label: string
  slot?: string
  skip?: boolean
  formatter?: (row: SettlementRecord) => string
}

const recMobileColumns: MobileCol[] = [
  { prop: 'symbol', label: '标的', skip: true },
  { prop: 'return_pct', label: '收益', skip: true },
  { prop: 'signal', label: '信号', slot: 'signal' },
  { prop: 'stated_confidence', label: '置信度', formatter: (row) => confidenceText(row.stated_confidence) },
  { prop: 'decision_date', label: '决策日', formatter: (row) => dateText(row.decision_date) },
  { prop: 'horizon_days', label: '持有期', formatter: (row) => horizonDaysLabel(row.horizon_days) },
  { prop: 'status', label: '状态', slot: 'status' },
  { prop: 'entry_price', label: '入场价', formatter: (row) => numText(row.entry_price) },
  { prop: 'exit_price', label: '出场价', formatter: (row) => numText(row.exit_price) },
  {
    prop: 'direction_hit',
    label: '方向',
    formatter: (row) => (row.direction_hit === null ? '—' : row.direction_hit ? '对' : '错')
  },
  { prop: 'error_type', label: '错题类型', formatter: (row) => errorTypeLabel(row.error_type) },
  { prop: 'failure_reason', label: '失败原因', formatter: (row) => row.failure_reason || '—' }
]

// ── 图表 ──────────────────────────────────────────────
const EMPTY_OPTION: EChartsOption = {
  title: { text: '暂无数据', left: 'center', top: 'center', textStyle: { color: '#999', fontSize: 14 } },
  xAxis: { show: false },
  yAxis: { show: false },
  series: []
}

const axisPercent = (v: number) => `${Math.round(v * 100)}%`

/** 置信度校准：x=桶均置信度（换算 0-1），y=桶命中率，附 y=x 对角参考线 */
const calibrationOption = computed<EChartsOption>(() => {
  const buckets = (scorecard.value?.calibration ?? []).filter((b) => b.hit_rate !== null)
  if (!buckets.length) return { ...EMPTY_OPTION }
  const points = buckets.map((b) => [b.avg_confidence / 100, b.hit_rate as number, b.count, b.bucket])
  return {
    grid: { left: 56, right: 24, top: 36, bottom: 40 },
    tooltip: {
      trigger: 'item',
      formatter: (p: unknown) => {
        const d = (p as { data: unknown }).data as [number, number, number, string]
        return [
          `置信度区间 ${d[3]}`,
          `样本 ${d[2]} 条`,
          `平均置信度 ${(d[0] * 100).toFixed(0)}%`,
          `实际命中率 ${(d[1] * 100).toFixed(1)}%`
        ].join('<br/>')
      }
    },
    xAxis: {
      type: 'value',
      min: 0,
      max: 1,
      name: '平均置信度',
      axisLabel: { formatter: axisPercent }
    },
    yAxis: {
      type: 'value',
      min: 0,
      max: 1,
      name: '实际命中率',
      axisLabel: { formatter: axisPercent }
    },
    series: [
      {
        type: 'scatter',
        name: '校准点',
        symbolSize: 12,
        itemStyle: { color: '#409eff' },
        data: points,
        label: {
          show: true,
          position: 'top',
          fontSize: 11,
          color: '#909399',
          formatter: (p: unknown) => `n=${((p as { data: unknown }).data as [number, number, number, string])[2]}`
        },
        markLine: {
          silent: true,
          symbol: ['none', 'none'],
          lineStyle: { type: 'dashed', color: '#c0c4cc' },
          label: { show: false },
          data: [[{ coord: [0, 0] }, { coord: [1, 1] }]]
        }
      }
    ]
  }
})

/** 命中率趋势：折线 + Wilson 95% 置信区间带（stack 两段：透明底线 + delta 面积） */
const trendOption = computed<EChartsOption>(() => {
  const trend = scorecard.value?.trend ?? []
  if (!trend.length || !trend.some((t) => t.hit_rate !== null)) return { ...EMPTY_OPTION }
  const months = trend.map((t) => t.month)
  const hitLine = trend.map((t) => t.hit_rate)
  const ciLow = trend.map((t) => t.ci_low)
  const ciDelta = trend.map((t) =>
    t.ci_low !== null && t.ci_high !== null ? Number((t.ci_high - t.ci_low).toFixed(6)) : null
  )
  return {
    grid: { left: 56, right: 24, top: 36, bottom: 40 },
    tooltip: {
      trigger: 'axis',
      formatter: (params: unknown) => {
        const list = Array.isArray(params) ? (params as { seriesName?: string; dataIndex: number }[]) : []
        const line = list.find((p) => p.seriesName === '命中率')
        if (!line) return ''
        const point = trend[line.dataIndex]
        if (!point) return ''
        const rows = [
          point.month,
          `样本 ${point.count} 条`,
          `命中率 ${pctText(point.hit_rate)}`
        ]
        if (point.ci_low !== null && point.ci_high !== null) {
          rows.push(
            `95% CI [${(point.ci_low * 100).toFixed(1)}%, ${(point.ci_high * 100).toFixed(1)}%]`
          )
        }
        if (point.avg_return_pct !== null) {
          rows.push(`平均收益 ${returnText(point.avg_return_pct)}`)
        }
        if (point.avg_alpha_pct !== null) {
          rows.push(`平均超额 ${returnText(point.avg_alpha_pct)}`)
        }
        return rows.join('<br/>')
      }
    },
    xAxis: { type: 'category', data: months },
    yAxis: {
      type: 'value',
      min: 0,
      max: 1,
      axisLabel: { formatter: axisPercent }
    },
    series: [
      {
        name: 'ci_base',
        type: 'line',
        stack: 'ci',
        data: ciLow,
        lineStyle: { opacity: 0 },
        symbol: 'none',
        silent: true
      },
      {
        name: '95% CI',
        type: 'line',
        stack: 'ci',
        data: ciDelta,
        lineStyle: { opacity: 0 },
        symbol: 'none',
        silent: true,
        areaStyle: { color: 'rgba(64, 158, 255, 0.15)' }
      },
      {
        name: '命中率',
        type: 'line',
        data: hitLine,
        connectNulls: false,
        symbolSize: 6,
        itemStyle: { color: '#409eff' }
      }
    ]
  }
})
</script>

<style scoped lang="scss">
.settlement-page {
  .page-header {
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
    gap: 12px;
    flex-wrap: wrap;
    margin-bottom: 16px;
  }

  .page-title {
    display: flex;
    align-items: center;
    gap: 8px;
    font-size: 24px;
    font-weight: 600;
    margin: 0 0 8px 0;
  }

  .page-description {
    color: var(--el-text-color-regular);
    margin: 0;
  }

  .page-header-right {
    display: flex;
    align-items: center;
    gap: 12px;
    flex-wrap: wrap;
  }

  .update-hint {
    font-size: 12px;
    color: var(--el-text-color-secondary);
    white-space: nowrap;
  }

  .tabs-card {
    margin-bottom: 16px;
  }

  .section-row {
    margin-top: 12px;
  }

  .stat-card {
    text-align: center;
  }

  .stat-value {
    font-size: 24px;
    font-weight: 600;
    color: var(--el-text-color-primary);
  }

  .stat-label {
    font-size: 13px;
    color: var(--el-text-color-regular);
    margin-top: 4px;
  }

  .stat-sub {
    font-size: 12px;
    color: var(--el-text-color-secondary);
    margin-top: 2px;
  }

  .hit-rate {
    padding: 8px 0;
  }

  .hit-rate-value {
    font-size: 36px;
    font-weight: 700;
    color: var(--el-color-primary);
    line-height: 1.2;

    &.empty {
      font-size: 22px;
      color: var(--el-text-color-secondary);
      font-weight: 500;
    }
  }

  .hit-rate-label {
    font-size: 13px;
    color: var(--el-text-color-regular);
    margin-top: 4px;
  }

  .hit-rate-meta {
    display: flex;
    flex-wrap: wrap;
    gap: 4px 16px;
    margin-top: 10px;
    font-size: 12px;
    color: var(--el-text-color-secondary);
  }

  .card-title {
    font-size: 14px;
    font-weight: 600;
    color: var(--el-text-color-primary);
  }

  .horizon-note {
    margin-top: 8px;
    font-size: 12px;
    color: var(--el-text-color-secondary);
  }

  .chart {
    height: 320px;
    width: 100%;
  }

  .symbol-text {
    font-weight: 600;
    color: var(--el-text-color-primary);
  }

  .name-text {
    margin-left: 6px;
    font-size: 12px;
    color: var(--el-text-color-secondary);
  }

  .pagination-wrapper {
    display: flex;
    justify-content: center;
    margin-top: 16px;
  }

  .error-desc {
    margin: 0 0 12px 0;
    font-size: 13px;
    color: var(--el-text-color-secondary);
  }

  .error-chip-row {
    display: flex;
    gap: 12px;
    margin-bottom: 12px;
  }

  .error-chip {
    display: flex;
    align-items: baseline;
    gap: 8px;
    min-height: 48px;
    padding: 6px 18px;
    border: 1px solid var(--el-border-color-light);
    border-radius: 8px;
    background: var(--el-bg-color);
    cursor: pointer;
    -webkit-tap-highlight-color: transparent;

    .chip-count {
      font-size: 22px;
      font-weight: 600;
      color: var(--el-text-color-primary);
    }

    .chip-label {
      font-size: 13px;
      color: var(--el-text-color-regular);
    }

    &.active {
      border-color: var(--el-color-primary);
      background: var(--el-color-primary-light-9);

      .chip-count,
      .chip-label {
        color: var(--el-color-primary);
      }
    }
  }

  .up {
    color: #e53935;
  }

  .down {
    color: #16a34a;
  }
}
</style>
