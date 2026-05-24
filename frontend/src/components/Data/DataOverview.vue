<template>
  <div class="data-overview" v-loading="loading">
    <!-- 质量总览 + 抽样校验 -->
    <div class="overview-top">
      <!-- 左：质量评分 -->
      <div class="quality-summary panel" v-if="overallScore !== null">
        <div class="summary-body">
          <div class="score-ring" :style="{ '--score-color': scoreColor, '--score-pct': overallScore + '%' }">
            <svg viewBox="0 0 100 100" class="ring-svg">
              <circle cx="50" cy="50" r="42" class="ring-bg" />
              <circle cx="50" cy="50" r="42" class="ring-fill" />
            </svg>
            <div class="score-text">
              <span class="score-value">{{ overallScore }}</span>
              <span class="score-unit">%</span>
            </div>
          </div>
          <div class="summary-info">
            <div class="summary-title">系统综合数据质量</div>
            <div class="summary-desc" :style="{ color: scoreColor }">
              评级：{{ scoreLabel }}
            </div>
            <div class="summary-meta">
              包含 {{ totalDomains }} 个数据域 | 共计 {{ formatNumber(totalRecords) }} 条底层记录
            </div>
            <p class="summary-explanation">
              该评分由各数据源的<strong style="color:var(--el-text-color-primary)">字段完整度</strong>和<strong style="color:var(--el-text-color-primary)">更新及时性</strong>加权计算得出。高评分意味着系统在执行量化回测或 AI 分析时，能够获取更准确、无偏差的底层支持。
            </p>
          </div>
        </div>
      </div>

      <!-- 右：数据抽样校验 -->
      <div class="stock-search panel">
        <div class="search-body">
          <div class="search-title">
            <el-icon :size="18" color="var(--el-color-primary)"><Microphone /></el-icon>
            底层数据抽样校验
          </div>
          <p class="search-desc">
            在进行大规模分析前，可通过输入特定标的（如 000001）快速抽样验证数据库中存储的实际落库数据，确保清洗与落库逻辑无误。
          </p>
          <div class="search-row">
            <el-input
              v-model="stockSymbol"
              placeholder="输入标的代码进行抽样..."
              @keyup.enter="handleStockSearch"
              clearable
            >
              <template #prefix>
                <el-icon><Search /></el-icon>
              </template>
            </el-input>
            <el-select v-model="stockDomain" clearable placeholder="全部数据域" style="width: 140px">
              <el-option v-for="d in domainOptions" :key="d.value" :label="d.label" :value="d.value" />
            </el-select>
            <el-button type="primary" :loading="stockLoading" @click="handleStockSearch">
              开始抽样
            </el-button>
          </div>
        </div>
      </div>
    </div>

    <!-- 股票查询结果 -->
    <transition name="el-zoom-in-top">
      <div v-if="stockData" class="stock-result panel">
        <div class="panel-header">
          <div class="panel-title">
            <el-icon :size="16"><DocumentChecked /></el-icon>
            标的 [{{ stockSymbol }}] 抽样校验报告
          </div>
          <el-button size="small" type="danger" plain @click="stockData = null">关闭校验结果</el-button>
        </div>
        <div class="panel-body">
          <el-alert
            v-if="Object.keys(stockData).length === 0"
            title="未命中任何数据"
            type="warning"
            description="数据库中不存在该标的的信息，请检查同步任务是否已执行或标的代码是否正确。"
            show-icon
            :closable="false"
          />
          <div v-for="(domainResult, domain) in (stockData as Record<string, any>)" :key="domain" class="result-domain">
            <div class="result-domain-header">
              <el-tag effect="dark" :type="domainResult.error ? 'danger' : 'success'">{{ domainLabel(domain as string) }}</el-tag>
              <span class="result-count">共检索到 {{ domainResult.total }} 条落库记录</span>
              <el-tag v-if="domainResult.error" type="danger" size="small" effect="light">{{ domainResult.error }}</el-tag>
            </div>
            <div v-if="!domainResult.error && domainResult.items?.length" class="result-table-wrap">
              <el-table :data="domainResult.items.slice(0, 10)" size="small" stripe border max-height="240">
                <el-table-column
                  v-for="col in getColumns(domainResult.items[0])"
                  :key="col"
                  :prop="col"
                  :label="col"
                  :min-width="120"
                >
                  <template #default="{ row }">{{ formatCell(row[col]) }}</template>
                </el-table-column>
              </el-table>
              <div class="table-footer-hint" v-if="domainResult.items.length > 10">
                * 仅展示前 10 条最新记录，其余 {{ domainResult.total - 10 }} 条已折叠。
              </div>
            </div>
          </div>
        </div>
      </div>
    </transition>

    <!-- 数据域卡片网格 -->
    <div class="section-title">
      <div class="title-left">
        <el-icon :size="18"><Grid /></el-icon>
        数据域落库状态总览
      </div>
      <div class="title-right">
        <span class="update-hint">实时监控各业务域的库内存量与更新鲜活度</span>
        <el-button size="small" plain type="primary" @click="loadData" :loading="loading">
          <el-icon><Refresh /></el-icon> 刷新状态
        </el-button>
      </div>
    </div>

    <div v-if="domainCards.length > 0" class="domain-grid">
      <div
        v-for="card in domainCards"
        :key="card.domain"
        class="domain-card"
        :class="card.healthClass"
      >
        <div class="card-header">
          <div class="card-name">
            <el-icon :size="18"><component :is="card.icon" /></el-icon>
            {{ card.label }}
          </div>
          <el-tooltip :content="card.healthText === '异常' ? '部分或全部首选数据源熔断，已降级' : card.healthText === '未同步' ? '该域尚未执行过同步任务，无健康数据' : '当前路由链路健康'" placement="top">
            <el-tag :type="card.healthTagType" size="small" effect="dark" round class="health-tag">
              {{ card.healthText }}
            </el-tag>
          </el-tooltip>
        </div>

        <p class="domain-business-desc">{{ domainDescription(card.domain) }}</p>

        <div class="card-metrics">
          <div class="metric-item">
            <span class="metric-value">{{ formatNumber(card.records) }}</span>
            <span class="metric-label">本地存量(条)</span>
          </div>
          <div class="metric-item">
            <span class="metric-value" :class="freshnessClass(card.freshnessMinutes)">{{ card.freshness }}</span>
            <span class="metric-label">数据鲜活度</span>
          </div>
          <div class="metric-item" v-if="card.completeness !== null">
            <span class="metric-value" :style="{ color: completenessColor(card.completeness) }">
              {{ Math.round(card.completeness * 100) }}%
            </span>
            <span class="metric-label">字段完整度</span>
          </div>
        </div>

        <!-- 完整度进度条 -->
        <div class="card-bar-wrap" v-if="card.completeness !== null">
          <div class="card-bar">
            <div
              class="card-bar-fill"
              :style="{ width: Math.round(card.completeness * 100) + '%', background: completenessColor(card.completeness) }"
            ></div>
          </div>
          <span class="bar-hint" v-if="card.completeness < 1">部分历史或罕见字段缺失</span>
          <span class="bar-hint" style="color:#7CB342" v-else>数据结构极其完整</span>
        </div>

        <div class="card-actions">
          <el-button size="small" type="primary" plain @click="handleQuickSync(card.domain)">
            <el-icon><RefreshRight /></el-icon> 触发增量同步
          </el-button>
          <el-button size="small" @click="handleViewData(card.domain)">
            <el-icon><Filter /></el-icon> 抽样校验
          </el-button>
        </div>
      </div>
    </div>

    <div v-else-if="!loading" class="empty-state">
      <el-icon :size="48" class="empty-icon"><WarningFilled /></el-icon>
      <p class="empty-title">当前市场暂无落库数据</p>
      <p class="empty-desc">请前往「同步管理」配置并执行同步任务以初始化数据库。</p>
      <el-button type="primary" @click="loadData">重新检查状态</el-button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, markRaw, watch } from 'vue'
import { ElMessage } from 'element-plus'
import {
  Monitor, Refresh, Search, Grid, Document, WarningFilled,
  InfoFilled, DataAnalysis, DataLine, Connection, Coin,
  ChatDotRound, Calendar, Microphone, DocumentChecked, RefreshRight, Filter
} from '@element-plus/icons-vue'
import {
  getDashboard, getQualityOverview, triggerSync, getStockData,
  type SourceHealthItem, type DomainStat,
  DOMAIN_LABELS,
} from '@/api/marketData'
import type { MarketCode } from '@/api/marketData'

const props = defineProps<{ market: MarketCode }>()
const emit = defineEmits<{
  statsLoaded: [stats: { healthySources: number; totalDomains: number; totalRecords: number; lastSync: string }]
}>()

// 域图标映射
const DOMAIN_ICON_MAP: Record<string, any> = {
  basic_info: markRaw(InfoFilled),
  daily_quotes: markRaw(DataLine),
  daily_indicators: markRaw(DataAnalysis),
  adj_factors: markRaw(Connection),
  financial_data: markRaw(Coin),
  market_quotes: markRaw(Monitor),
  news: markRaw(ChatDotRound),
  trade_calendar: markRaw(Calendar),
  corporate_actions: markRaw(Document),
}

const DOMAIN_DESCRIPTIONS: Record<string, string> = {
  basic_info: '构建本地标的池，存储股票代码、名称、行业及上市状态等底层基建信息。',
  daily_quotes: '落地每日 OHLC、成交量等行情序列，是技术分析代理节点的核心输入。',
  daily_indicators: '存储 PE、PB、换手率等估值指标，用于基本面筛股和流动性分析。',
  adj_factors: '除权除息修复因子，保证收益率计算与长线趋势分析的准确性。',
  financial_data: '定期财报资产负债、利润等三大表数据，支撑财务健康度排雷。',
  market_quotes: '盘中实时快照数据缓存，提供当前最新盘口和现价。',
  news: '财经新闻与舆情文本数据，用于大模型情绪分析与事件驱动打分。',
  trade_calendar: '市场开闭市时间表，用于对齐时间序列和排除非交易日。',
  corporate_actions: '分红、配股等公司行为记录，用于追溯资本变动。'
}

interface DomainCard {
  domain: string
  label: string
  icon: any
  records: number
  lastUpdated: string | null
  freshness: string
  freshnessMinutes: number
  healthSources: SourceHealthItem[]
  healthTagType: 'success' | 'warning' | 'danger' | 'info'
  healthText: string
  healthClass: string
  completeness: number | null
}

const loading = ref(false)
const healthData = ref<SourceHealthItem[]>([])
const domainStats = ref<Record<string, DomainStat>>({})
const qualityData = ref<Record<string, any>>({})

// 股票查询
const stockSymbol = ref('')
const stockDomain = ref<string | undefined>(undefined)
const stockLoading = ref(false)
const stockData = ref<any>(null)

const domainOptions = computed(() => [
  { value: 'basic_info', label: '基础信息' },
  { value: 'daily_quotes', label: '日K线' },
  { value: 'daily_indicators', label: '每日指标' },
  { value: 'adj_factors', label: '复权因子' },
  { value: 'financial_data', label: '财务数据' },
])

// 质量评分
const totalDomains = computed(() => Object.keys(domainStats.value).length)
const totalRecords = computed(() =>
  Object.values(domainStats.value).reduce((sum, s) => sum + s.records, 0),
)

const overallScore = computed(() => {
  const entries = Object.entries(qualityData.value as Record<string, any>)
  if (entries.length === 0) return null
  const total = entries.reduce((sum, [, info]) => sum + (info.completeness ?? 0), 0)
  return Math.round((total / entries.length) * 100)
})

const scoreColor = computed(() => {
  const s = overallScore.value ?? 0
  if (s >= 95) return '#7CB342'
  if (s >= 80) return '#C5A55A'
  if (s >= 60) return '#D4AF37'
  return '#E57373'
})

const scoreLabel = computed(() => {
  const s = overallScore.value ?? 0
  if (s >= 95) return '优秀'
  if (s >= 80) return '良好'
  if (s >= 60) return '一般'
  return '需改善'
})

function domainLabel(domain: string) { return DOMAIN_LABELS[domain] || domain }
function domainDescription(domain: string) { return DOMAIN_DESCRIPTIONS[domain] || '暂无业务描述' }

function formatNumber(n: number): string {
  if (n >= 1_000_000) return (n / 1_000_000).toFixed(1) + 'M'
  if (n >= 1_000) return (n / 1_000).toFixed(0) + 'K'
  return String(n)
}

function freshnessClass(minutes: number): string {
  if (minutes < 0) return 'color-danger'
  if (minutes <= 60) return 'color-success'
  if (minutes <= 1440) return 'color-warning'
  return 'color-danger'
}

function completenessColor(c: number): string {
  if (c >= 0.99) return '#7CB342'
  if (c >= 0.8) return '#C5A55A'
  if (c >= 0.5) return '#D4AF37'
  return '#E57373'
}

function getRelativeTime(iso: string | null): { text: string; minutes: number } {
  if (!iso) return { text: '暂无数据', minutes: -1 }
  const diffMs = Date.now() - new Date(iso).getTime()
  const diffMin = Math.floor(diffMs / 60_000)
  if (diffMin < 1) return { text: '刚刚', minutes: 0 }
  if (diffMin < 60) return { text: `${diffMin}分钟前`, minutes: diffMin }
  const diffHr = Math.floor(diffMin / 60)
  if (diffHr < 24) return { text: `${diffHr}小时前`, minutes: diffMin }
  const diffDay = Math.floor(diffHr / 24)
  if (diffDay < 30) return { text: `${diffDay}天前`, minutes: diffMin }
  return { text: new Date(iso).toLocaleDateString('zh-CN'), minutes: diffMin }
}

function getDomainHealth(sources: SourceHealthItem[], hasRecords: boolean): { tagType: 'success' | 'warning' | 'danger' | 'info'; text: string; cls: string } {
  if (sources.length === 0) {
    // 无健康监控数据时，根据域是否有落库记录推断状态：
    // 有记录 → 数据源曾经正常工作过，推断为"正常"
    // 无记录 → 从未同步过，推断为"未同步"
    if (hasRecords) return { tagType: 'success', text: '正常', cls: 'state-healthy' }
    return { tagType: 'info', text: '未同步', cls: '' }
  }
  const hasUnhealthy = sources.some(s => s.circuit_state === 'open')
  const hasHalfOpen = sources.some(s => s.circuit_state === 'half_open')
  if (hasUnhealthy) return { tagType: 'danger', text: '异常', cls: 'state-error' }
  if (hasHalfOpen) return { tagType: 'warning', text: '恢复中', cls: 'state-warning' }
  return { tagType: 'success', text: '正常', cls: 'state-healthy' }
}

const domainCards = computed<DomainCard[]>(() => {
  const domains = Object.keys(domainStats.value)
  if (domains.length === 0) return []

  return domains.map(domain => {
    const stat = domainStats.value[domain]
    const sources = healthData.value.filter(h => h.domain === domain)
    const quality = (qualityData.value as Record<string, any>)?.[domain]
    const health = getDomainHealth(sources, (stat?.records ?? 0) > 0)
    const freshness = getRelativeTime(stat?.last_updated ?? null)

    return {
      domain,
      label: domainLabel(domain),
      icon: DOMAIN_ICON_MAP[domain] || markRaw(Document),
      records: stat?.records ?? 0,
      lastUpdated: stat?.last_updated ?? null,
      freshness: freshness.text,
      freshnessMinutes: freshness.minutes,
      healthSources: sources,
      healthTagType: health.tagType,
      healthText: health.text,
      healthClass: health.cls,
      completeness: quality?.completeness ?? null,
    }
  })
})

async function loadData() {
  loading.value = true
  try {
    const [dashRes, qualRes] = await Promise.allSettled([
      getDashboard(props.market),
      getQualityOverview(props.market),
    ])

    if (dashRes.status === 'fulfilled' && dashRes.value.success) {
      healthData.value = dashRes.value.data?.source_health || []
      domainStats.value = dashRes.value.data?.domain_stats || {}
    }

    if (qualRes.status === 'fulfilled' && qualRes.value.success) {
      qualityData.value = qualRes.value.data || {}
    }

    // 向父组件发送统计
    const healthyCount = healthData.value.filter(h => h.circuit_state === 'closed').length
    const records = Object.values(domainStats.value).reduce((sum, s) => sum + s.records, 0)
    const allUpdated = Object.values(domainStats.value)
      .map(s => s.last_updated).filter(Boolean).sort().reverse() as string[]
    const lastSync = allUpdated.length > 0 ? getRelativeTime(allUpdated[0]).text : '--'

    emit('statsLoaded', {
      healthySources: healthyCount,
      totalDomains: Object.keys(domainStats.value).length,
      totalRecords: records,
      lastSync,
    })
  } catch {
    ElMessage.error('加载数据失败')
  } finally {
    loading.value = false
  }
}

async function handleQuickSync(domain: string) {
  try {
    await triggerSync(props.market, domain, 'incremental')
    ElMessage.success(`${domainLabel(domain)} 同步已触发`)
  } catch {
    ElMessage.error('触发同步失败')
  }
}

function handleViewData(domain: string) {
  stockDomain.value = domain
  if (stockSymbol.value) {
    handleStockSearch()
  } else {
    ElMessage.info('请在上方输入股票代码后查询')
  }
}

async function handleStockSearch() {
  if (!stockSymbol.value.trim()) return
  stockLoading.value = true
  try {
    const res = await getStockData(props.market, stockSymbol.value.trim(), {
      domain: stockDomain.value,
      page: 1,
      page_size: 20,
    })
    if (res.success) {
      stockData.value = res.data
      if (!stockData.value || Object.keys(stockData.value).length === 0) {
        ElMessage.warning('未找到数据，请检查股票代码')
        stockData.value = null
      }
    } else {
      stockData.value = null
    }
  } catch {
    stockData.value = null
  } finally {
    stockLoading.value = false
  }
}

function getColumns(firstItem: any): string[] {
  if (!firstItem || typeof firstItem !== 'object') return []
  return Object.keys(firstItem).filter(k => !['_id', 'id'].includes(k))
}

function formatCell(val: any): string {
  if (val === null || val === undefined) return '-'
  if (typeof val === 'number') {
    return Number.isInteger(val) ? val.toLocaleString() : val.toFixed(4)
  }
  if (typeof val === 'object') return JSON.stringify(val)
  return String(val)
}

watch(() => props.market, () => {
  stockData.value = null
  stockSymbol.value = ''
  loadData()
})

onMounted(loadData)
</script>

<style scoped lang="scss">
.data-overview {
  animation: fadeIn 0.4s ease-out;
}

@keyframes fadeIn {
  from { opacity: 0; transform: translateY(10px); }
  to { opacity: 1; transform: translateY(0); }
}

/* ── 顶部双列布局 ── */
.overview-top {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 20px;
  margin-bottom: 24px;
}

.panel {
  background: var(--el-bg-color);
  border-radius: 16px;
  border: 1px solid var(--el-border-color-lighter);
  overflow: hidden;
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.02);
  transition: box-shadow 0.3s ease;
  
  &:hover {
    box-shadow: 0 8px 24px rgba(0, 0, 0, 0.06);
  }
}

.panel-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 16px 20px;
  border-bottom: 1px solid var(--el-border-color-extra-light);
  background: var(--el-bg-color);

  .panel-title {
    display: flex;
    align-items: center;
    gap: 8px;
    font-weight: 600;
    font-size: 15px;
    color: var(--el-text-color-primary);
  }
}

.panel-body {
  padding: 20px;
}

/* ── 质量评分 ── */
.quality-summary .summary-body {
  display: flex;
  align-items: center;
  gap: 24px;
  padding: 24px;
  background: linear-gradient(to right, #ffffff, var(--el-bg-color));
}

.score-ring {
  position: relative;
  width: 80px;
  height: 80px;
  flex-shrink: 0;

  .ring-svg {
    width: 100%;
    height: 100%;
    transform: rotate(-90deg);
  }

  .ring-bg {
    fill: none;
    stroke: var(--el-border-color-lighter);
    stroke-width: 6;
  }

  .ring-fill {
    fill: none;
    stroke: var(--score-color);
    stroke-width: 6;
    stroke-linecap: round;
    stroke-dasharray: 264;
    stroke-dashoffset: calc(264 - 264 * var(--score-pct) / 100);
    transition: stroke-dashoffset 0.8s ease;
  }

  .score-text {
    position: absolute;
    inset: 0;
    display: flex;
    align-items: center;
    justify-content: center;
    margin-top: -2px; // 修复文字偏上溢出的问题

    .score-value {
      font-size: 26px;
      font-weight: 800;
      color: var(--score-color);
      line-height: 1;
    }
    .score-unit {
      font-size: 14px;
      font-weight: 700;
      color: var(--score-color);
      margin-left: 2px;
      margin-top: 4px;
    }
  }
}

.summary-info {
  .summary-title {
    font-size: 15px;
    font-weight: 600;
    color: var(--el-text-color-primary);
    margin-bottom: 4px;
  }
  .summary-desc {
    font-size: 14px;
    font-weight: 600;
    margin-bottom: 6px;
  }
  .summary-meta {
    font-size: 12px;
    color: var(--el-text-color-secondary);
  }
  .summary-explanation {
    margin: 12px 0 0 0;
    font-size: 13px;
    color: var(--el-text-color-regular);
    line-height: 1.5;
    background: rgba(0, 0, 0, 0.02);
    padding: 10px;
    border-radius: 6px;
  }
}

/* ── 股票查询 ── */
.stock-search .search-body {
  padding: 20px;
}

.search-title {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 15px;
  font-weight: 700;
  color: var(--el-text-color-primary);
  margin-bottom: 8px;
}

.search-desc {
  font-size: 13px;
  color: var(--el-text-color-secondary);
  margin: 0 0 16px 0;
  line-height: 1.5;
}

.search-row {
  display: flex;
  gap: 10px;

  .el-input {
    flex: 1;
  }
}

/* ── 查询结果 ── */
.stock-result {
  margin-bottom: 24px;
}

.result-domain {
  margin-bottom: 16px;

  &:last-child { margin-bottom: 0; }
}

.result-domain-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 10px;

  .result-count {
    font-size: 12px;
    color: var(--el-text-color-secondary);
  }
}

.result-table-wrap {
  border-radius: 8px;
  overflow: hidden;

  .table-footer-hint {
    padding: 8px 12px;
    font-size: 12px;
    color: var(--el-text-color-secondary);
    background: var(--el-bg-color);
    border: 1px solid var(--el-border-color-lighter);
    border-top: none;
    border-bottom-left-radius: 8px;
    border-bottom-right-radius: 8px;
  }
}

/* ── 区域标题 ── */
.section-title {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 20px;

  .title-left {
    display: flex;
    align-items: center;
    gap: 8px;
    font-size: 16px;
    font-weight: 600;
    color: var(--el-text-color-primary);
  }

  .title-right {
    display: flex;
    align-items: center;
    gap: 16px;

    .update-hint {
      font-size: 13px;
      color: var(--el-text-color-secondary);
    }
  }
}

/* ── 域卡片网格 ── */
.domain-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
  gap: 20px;
}

.domain-card {
  padding: 24px;
  border-radius: 16px;
  border: 1px solid var(--el-border-color-lighter);
  background: var(--el-bg-color);
  transition: all 0.3s cubic-bezier(0.25, 0.8, 0.25, 1);
  display: flex;
  flex-direction: column;

  &:hover {
    box-shadow: 0 12px 24px rgba(0, 0, 0, 0.06);
    transform: translateY(-4px);
    border-color: var(--el-color-primary-light-5);
  }

  &.state-healthy { border-top: 4px solid #7CB342; }
  &.state-warning { border-top: 4px solid #D4AF37; }
  &.state-error { border-top: 4px solid #E57373; }
}

.card-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  margin-bottom: 12px;

  .card-name {
    display: flex;
    align-items: center;
    gap: 8px;
    font-weight: 700;
    font-size: 18px;
    color: var(--el-text-color-primary);
  }

  .health-tag {
    cursor: help;
  }
}

.domain-business-desc {
  font-size: 13px;
  color: var(--el-text-color-regular);
  line-height: 1.5;
  margin: 0 0 20px;
  min-height: 40px;
}

.card-metrics {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 12px;
  margin-bottom: 16px;
  background: var(--el-bg-color);
  padding: 12px;
  border-radius: 8px;
}

.metric-item {
  text-align: center;

  .metric-value {
    display: block;
    font-size: 16px;
    font-weight: 700;
    color: var(--el-text-color-primary);
    line-height: 1.3;

    &.color-success { color: #7CB342; }
    &.color-warning { color: #D4AF37; }
    &.color-danger { color: #E57373; }
  }

  .metric-label {
    display: block;
    font-size: 12px;
    color: var(--el-text-color-secondary);
    margin-top: 4px;
  }
}

.card-bar-wrap {
  margin-bottom: 20px;

  .card-bar {
    height: 6px;
    border-radius: 3px;
    background: var(--el-fill-color);
    overflow: hidden;
    margin-bottom: 6px;

    .card-bar-fill {
      height: 100%;
      border-radius: 3px;
      transition: width 0.6s ease;
    }
  }

  .bar-hint {
    display: block;
    font-size: 11px;
    color: var(--el-text-color-secondary);
  }
}

.card-actions {
  display: flex;
  gap: 10px;
  margin-top: auto;
}

/* ── 空状态 ── */
.empty-state {
  text-align: center;
  padding: 48px 20px;
  color: var(--el-text-color-secondary);

  .empty-icon {
    color: var(--el-text-color-placeholder);
    margin-bottom: 12px;
  }

  p { margin: 0 0 8px; font-size: 14px; }
}

/* ── 响应式 ── */
@media (max-width: 900px) {
  .overview-top {
    grid-template-columns: 1fr;
  }
  .domain-grid {
    grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
  }
}
</style>
