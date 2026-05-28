<template>
  <div class="source-config" v-loading="loading">
    <!-- 市场标识横幅 -->
    <div class="market-banner" :class="props.market">
      <div class="market-icon">
        {{ marketFlag }}
      </div>
      <div class="market-info">
        <h2 class="market-name">{{ marketName }} 数据源配置</h2>
        <p class="market-desc">
          配置 {{ marketName }} 各数据域的优先获取链路。当首选数据源熔断或不可用时，系统将自动降级至备用源。
        </p>
      </div>
    </div>

    <!-- 源健康告警 -->
    <transition name="fade">
      <div v-if="unhealthySources.length > 0" class="health-alerts">
        <div class="alert-header">
          <el-icon :size="18" color="#E57373"><WarningFilled /></el-icon>
          <span>{{ unhealthySources.length }} 个数据源出现异常，已触发熔断或处于半开状态</span>
        </div>
        <div class="alert-list">
          <div v-for="h in unhealthySources" :key="`${h.source}-${h.domain}`" class="alert-item">
            <div class="alert-info">
              <el-tag :type="h.circuit_state === 'open' ? 'danger' : 'warning'" size="small" effect="dark" round>
                {{ h.circuit_state === 'open' ? '熔断' : '半开' }}
              </el-tag>
              <span class="alert-source">{{ h.source?.toUpperCase() }}</span>
              <el-icon class="alert-arrow"><Right /></el-icon>
              <span class="alert-domain">{{ domainLabel(h.domain) }}</span>
            </div>
            <div class="alert-metrics">
              <span class="metric-badge">成功率: <strong :class="{ 'text-danger': h.success_rate_1h < 0.8 }">{{ formatPercent(h.success_rate_1h) }}</strong></span>
              <span class="metric-badge">连续失败: <strong>{{ h.consecutive_failures }} 次</strong></span>
            </div>
            <el-button type="warning" size="small" plain round @click="handleReset(h)">
              <el-icon><RefreshRight /></el-icon> 重置熔断器
            </el-button>
          </div>
        </div>
      </div>
    </transition>

    <!-- 域配置列表 -->
    <div class="section-header">
      <div class="section-title">
        <el-icon :size="18"><Connection /></el-icon>
        数据域路由策略
      </div>
      <div class="header-actions">
        <el-button size="small" type="primary" plain round @click="loadConfig" :loading="loading">
          <el-icon><Refresh /></el-icon> 刷新配置
        </el-button>
      </div>
    </div>

    <div v-if="configDomains.length > 0" class="config-grid">
      <div v-for="item in configDomains" :key="item.domain" class="domain-card">
        <!-- 域头部：名称与说明 -->
        <div class="domain-header">
          <div class="domain-title-area">
            <h3 class="domain-name">{{ item.label }}</h3>
            <el-tag size="small" type="info" effect="plain" class="domain-code">{{ item.domain }}</el-tag>
          </div>
          <el-button class="edit-btn" size="small" text type="primary" @click="openPriorityEditor(item)">
            <el-icon><Setting /></el-icon> 调整优先级
          </el-button>
        </div>
        
        <p class="domain-desc">{{ domainDescription(item.domain) }}</p>

        <!-- 当前优先级链 -->
        <div class="priority-section">
          <div class="section-label">路由优先级 (Fallback Chain):</div>
          <div class="priority-chain" v-if="item.priority.length > 0">
            <template v-for="(p, idx) in item.priority" :key="idx">
              <div class="priority-step" :class="{ 'is-primary': idx === 0 }">
                <span class="step-rank">{{ idx + 1 }}</span>
                <span class="step-name">{{ p.toUpperCase() }}</span>
              </div>
              <el-icon v-if="idx < item.priority.length - 1" class="chain-arrow"><Right /></el-icon>
            </template>
          </div>
          <div v-else class="no-priority">未配置路由，将导致该域数据无法获取。</div>
        </div>

        <!-- 能力矩阵 -->
        <div class="capability-section">
          <div class="section-label">支持的数据源 (Capability):</div>
          <div class="capability-list">
            <el-tooltip
              v-for="src in item.sources"
              :key="src.name"
              :content="`${src.name.toUpperCase()} 提供 ${src.levelLabel} 支持`"
              placement="top"
            >
              <div class="source-tag" :class="src.levelClass">
                <span class="source-tag-name">{{ src.name.toUpperCase() }}</span>
                <el-icon v-if="src.level === 'full'" class="source-tag-icon"><Check /></el-icon>
                <el-icon v-else-if="src.level === 'partial'" class="source-tag-icon"><Minus /></el-icon>
              </div>
            </el-tooltip>
          </div>
        </div>
      </div>
    </div>

    <div v-else-if="!loading" class="empty-state">
      <el-empty description="该市场暂无数据源配置信息" />
    </div>

    <!-- 图例说明 -->
    <div class="legend-panel">
      <div class="legend-title"><el-icon><InfoFilled /></el-icon> 状态说明</div>
      <div class="legend-items">
        <div class="legend-item">
          <div class="source-tag full"><span class="source-tag-name">数据源</span><el-icon><Check /></el-icon></div>
          <span class="legend-text">完整支持：可提供该域的全部字段和历史数据。</span>
        </div>
        <div class="legend-item">
          <div class="source-tag partial"><span class="source-tag-name">数据源</span><el-icon><Minus /></el-icon></div>
          <span class="legend-text">部分支持：缺少某些字段或历史数据长度有限。</span>
        </div>
        <div class="legend-item">
          <div class="priority-step is-primary"><span class="step-rank">1</span><span class="step-name">首选源</span></div>
          <span class="legend-text">首选数据源：系统请求该域数据时的第一选择。</span>
        </div>
      </div>
    </div>

    <!-- 编辑优先级对话框 -->
    <el-dialog
      v-model="showEditor"
      :title="`调整路由优先级 — ${editingDomainLabel}`"
      width="500px"
      :close-on-click-modal="false"
      custom-class="priority-dialog"
    >
      <div class="editor-header">
        <el-alert 
          title="配置原则" 
          type="info" 
          description="将稳定性高、字段全的源设为首选(1)。当首选源熔断时，系统按此列表顺序向下尝试获取。" 
          show-icon 
          :closable="false"
        />
      </div>
      <div class="editor-list">
        <div v-for="(src, idx) in editingPriority" :key="src" class="editor-item">
          <div class="editor-item-left">
            <span class="editor-rank" :class="{ 'is-first': idx === 0 }">{{ idx + 1 }}</span>
            <span class="editor-source">{{ src.toUpperCase() }}</span>
            <el-tag v-if="idx === 0" size="small" type="success" effect="plain" style="margin-left: 8px">首选</el-tag>
          </div>
          <div class="editor-arrows">
            <el-button :disabled="idx === 0" size="small" @click="moveUp(idx)" plain>
              <el-icon><ArrowUp /></el-icon> 上移
            </el-button>
            <el-button :disabled="idx === editingPriority.length - 1" size="small" @click="moveDown(idx)" plain>
              <el-icon><ArrowDown /></el-icon> 下移
            </el-button>
          </div>
        </div>
      </div>
      <template #footer>
        <div class="dialog-footer">
          <el-button @click="showEditor = false" round>取消</el-button>
          <el-button type="primary" :loading="saving" @click="savePriority" round>确认保存</el-button>
        </div>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue'
import { ElMessage } from 'element-plus'
import {
  Connection, Refresh, RefreshRight, WarningFilled, Check, Minus, Right,
  Setting, ArrowUp, ArrowDown, InfoFilled
} from '@element-plus/icons-vue'
import {
  getSourceConfig, updateSourcePriority, getSourcesHealth, resetCircuitBreaker,
  type SourceHealthItem,
  DOMAIN_LABELS,
} from '@/api/marketData'
import type { MarketCode } from '@/api/marketData'

const props = defineProps<{ market: MarketCode }>()

const DOMAIN_DESCRIPTIONS: Record<string, string> = {
  basic_info: '包含股票代码、名称、所属行业、上市状态等静态信息，是系统构建标的池的基础前提。',
  daily_quotes: '每日开高低收（OHLC）、成交量、成交额等核心行情数据，主要用于技术分析和趋势回测。',
  daily_indicators: '市盈率(PE)、市净率(PB)、换手率、总市值等每日动态更新的衍生估值和流动性指标。',
  adj_factors: '前复权/后复权因子数据，用于修复因分红派息、拆股等引起的K线价格跳空，保证收益率计算正确。',
  financial_data: '利润表、资产负债表、现金流量表等定期财报数据，用于基本面深度分析与排雷。',
  market_quotes: '盘中实时行情快照，提供最新的买卖盘口和现价，用于高频监控和交易决策。',
  news: '与标的相关的财经新闻、公司公告和舆情动态，用于情绪分析和事件驱动策略。',
  trade_calendar: '交易所的开市、休市日历安排，用于对齐不同市场的时间序列和排除非交易日。',
  corporate_actions: '分红、派息、拆股、合股等公司行为的具体记录，用于追溯资本变动历史。',
  intraday_quotes: '分时级别的 Tick/分钟线行情数据，提供更细粒度的盘中价格走势，用于日内分析和高频策略。',
  money_flow: '个股及行业板块的主力资金流入流出数据，用于判断资金动向和市场热点轮动。',
  margin_trading: '融资融券余额、买入偿还等两融数据，用于衡量市场杠杆水平和多空力量对比。',
  dragon_tiger: '交易所公开披露的龙虎榜数据，记录活跃营业部买卖明细，用于跟踪游资与机构动向。',
  block_trade: '达到大宗交易门槛的大额成交记录，包含成交价、成交量、买卖方席位等信息。',
  connect_status: '沪港通/深港通互联互通额度使用情况，用于监控跨境资金通道状态。',
  southbound_holding: '南向资金持股明细，反映内地投资者对港股的持仓变动和配置偏好。',
  pre_post_market: '美股盘前盘后交易行情数据，用于追踪非常规交易时段的价格波动。',
}

interface SourceInfo {
  name: string
  level: string
  levelLabel: string
  levelClass: string
}

interface ConfigDomain {
  domain: string
  label: string
  sources: SourceInfo[]
  priority: string[]
}

const loading = ref(false)
const matrixRows = ref<Record<string, Record<string, string>>>({})
const priorities = ref<Record<string, string[]>>({})
const healthData = ref<SourceHealthItem[]>([])

// 编辑优先级
const showEditor = ref(false)
const editingDomain = ref('')
const editingDomainLabel = ref('')
const editingPriority = ref<string[]>([])
const saving = ref(false)

const marketName = computed(() => {
  if (props.market === 'cn') return 'A股'
  if (props.market === 'hk') return '港股'
  if (props.market === 'us') return '美股'
  return '未知市场'
})

const marketFlag = computed(() => {
  if (props.market === 'cn') return '🇨🇳'
  if (props.market === 'hk') return '🇭🇰'
  if (props.market === 'us') return '🇺🇸'
  return '🌐'
})

function domainLabel(domain: string) { return DOMAIN_LABELS[domain] || domain }
function domainDescription(domain: string) { return DOMAIN_DESCRIPTIONS[domain] || '该数据域提供相关的专业数据支撑。' }
function formatPercent(v: number) { return (v * 100).toFixed(1) + '%' }

function levelInfo(level: string) {
  if (level === 'full') return { label: '完整', cls: 'full' }
  if (level === 'partial') return { label: '部分', cls: 'partial' }
  return { label: '不支持', cls: 'none' }
}

const unhealthySources = computed(() =>
  healthData.value.filter(h => h.circuit_state === 'open' || h.circuit_state === 'half_open'),
)

const configDomains = computed<ConfigDomain[]>(() => {
  return Object.entries(matrixRows.value).map(([domain, sources]) => {
    const sourceList: SourceInfo[] = Object.entries(sources).map(([name, level]) => {
      const li = levelInfo(level)
      return { name, level, levelLabel: li.label, levelClass: li.cls }
    })

    // 排序：完整的排前面
    const levelOrder: Record<string, number> = { full: 0, partial: 1, none: 2 }
    sourceList.sort((a, b) => (levelOrder[a.level] ?? 9) - (levelOrder[b.level] ?? 9))

    return {
      domain,
      label: domainLabel(domain),
      sources: sourceList,
      priority: priorities.value[domain] || [],
    }
  })
})

async function loadConfig() {
  loading.value = true
  try {
    const [configRes, healthRes] = await Promise.allSettled([
      getSourceConfig(props.market),
      getSourcesHealth(props.market),
    ])

    if (configRes.status === 'fulfilled' && configRes.value.success) {
      matrixRows.value = configRes.value.data?.capability_matrix || {}
      priorities.value = configRes.value.data?.priorities || {}
    }

    if (healthRes.status === 'fulfilled' && healthRes.value.success) {
      healthData.value = healthRes.value.data || []
    }
  } catch { /* 静默 */ } finally {
    loading.value = false
  }
}

function openPriorityEditor(item: ConfigDomain) {
  editingDomain.value = item.domain
  editingDomainLabel.value = item.label
  editingPriority.value = [...item.priority]
  showEditor.value = true
}

function moveUp(idx: number) {
  if (idx <= 0) return
  const list = [...editingPriority.value]
  ;[list[idx - 1], list[idx]] = [list[idx], list[idx - 1]]
  editingPriority.value = list
}

function moveDown(idx: number) {
  if (idx >= editingPriority.value.length - 1) return
  const list = [...editingPriority.value]
  ;[list[idx], list[idx + 1]] = [list[idx + 1], list[idx]]
  editingPriority.value = list
}

async function savePriority() {
  saving.value = true
  try {
    await updateSourcePriority(props.market, editingDomain.value, editingPriority.value)
    ElMessage.success(`${editingDomainLabel.value} 优先级已更新`)
    priorities.value[editingDomain.value] = [...editingPriority.value]
    showEditor.value = false
  } catch {
    ElMessage.error('更新优先级失败')
  } finally {
    saving.value = false
  }
}

async function handleReset(h: SourceHealthItem) {
  try {
    await resetCircuitBreaker(props.market, h.source, h.domain)
    ElMessage.success(`${h.source}/${domainLabel(h.domain)} 熔断器已重置`)
    loadConfig()
  } catch {
    ElMessage.error('重置失败')
  }
}

watch(() => props.market, () => {
  loadConfig()
})

onMounted(loadConfig)
</script>

<style scoped lang="scss">
.source-config {
  display: flex;
  flex-direction: column;
  gap: 24px;
  animation: fadeIn 0.4s ease-out;
}

@keyframes fadeIn {
  from { opacity: 0; transform: translateY(10px); }
  to { opacity: 1; transform: translateY(0); }
}

/* ── 市场横幅 ── */
.market-banner {
  display: flex;
  align-items: center;
  gap: 20px;
  padding: 24px 30px;
  border-radius: 16px;
  color: #fff;
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.08);

  &.cn { background: linear-gradient(135deg, #C5A55A 0%, #9E7E3E 100%); }
  &.hk { background: linear-gradient(135deg, #B76E79 0%, #9E5A66 100%); }
  &.us { background: linear-gradient(135deg, #B8A070 0%, #9E9688 100%); }

  .market-icon {
    font-size: 48px;
    line-height: 1;
    filter: drop-shadow(0 4px 8px rgba(0,0,0,0.2));
  }

  .market-info {
    flex: 1;
    .market-name {
      margin: 0 0 8px;
      font-size: 24px;
      font-weight: 700;
      letter-spacing: 1px;
    }
    .market-desc {
      margin: 0;
      font-size: 14px;
      opacity: 0.9;
      line-height: 1.5;
    }
  }
}

/* ── 健康告警 ── */
.health-alerts {
  background: #FBE8E8;
  border-left: 4px solid #E57373;
  border-radius: 8px;
  padding: 16px 24px;
  box-shadow: 0 2px 12px rgba(229, 115, 115, 0.1);

  .alert-header {
    display: flex;
    align-items: center;
    gap: 10px;
    font-weight: 600;
    font-size: 15px;
    color: #E57373;
    margin-bottom: 16px;
  }

  .alert-list {
    display: flex;
    flex-direction: column;
    gap: 12px;
  }

  .alert-item {
    display: flex;
    align-items: center;
    justify-content: space-between;
    background: #fff;
    padding: 12px 16px;
    border-radius: 8px;
    border: 1px solid #ffcdd2;

    .alert-info {
      display: flex;
      align-items: center;
      gap: 10px;
      .alert-source { font-weight: 700; color: #333; }
      .alert-arrow { color: #999; }
      .alert-domain { font-size: 13px; color: #666; background: #f5f7fa; padding: 2px 8px; border-radius: 4px; }
    }

    .alert-metrics {
      display: flex;
      gap: 16px;
      .metric-badge {
        font-size: 13px;
        color: #555;
        background: #fdfdfd;
        padding: 4px 10px;
        border-radius: 6px;
        border: 1px solid #eee;
        .text-danger { color: #E57373; }
      }
    }
  }
}

/* ── 区域头部 ── */
.section-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  border-bottom: 2px solid var(--el-border-color-lighter);
  padding-bottom: 12px;

  .section-title {
    display: flex;
    align-items: center;
    gap: 8px;
    font-size: 18px;
    font-weight: 600;
    color: var(--el-text-color-primary);
  }
}

/* ── 域配置网格 ── */
.config-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(400px, 1fr));
  gap: 20px;
}

.domain-card {
  background: var(--el-bg-color);
  border: 1px solid var(--el-border-color-light);
  border-radius: 12px;
  padding: 20px;
  transition: all 0.3s cubic-bezier(0.25, 0.8, 0.25, 1);
  display: flex;
  flex-direction: column;

  &:hover {
    transform: translateY(-4px);
    box-shadow: 0 12px 24px rgba(0, 0, 0, 0.06);
    border-color: var(--el-color-primary-light-5);
  }

  .domain-header {
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
    margin-bottom: 8px;

    .domain-title-area {
      display: flex;
      align-items: center;
      gap: 10px;
      
      .domain-name {
        margin: 0;
        font-size: 18px;
        font-weight: 600;
        color: var(--el-text-color-primary);
      }
      .domain-code { font-family: monospace; }
    }
  }

  .domain-desc {
    margin: 0 0 20px 0;
    font-size: 13px;
    color: var(--el-text-color-regular);
    line-height: 1.5;
    min-height: 40px;
  }

  .section-label {
    font-size: 12px;
    font-weight: 600;
    color: var(--el-text-color-secondary);
    margin-bottom: 10px;
    text-transform: uppercase;
  }

  .priority-section {
    margin-bottom: 20px;
    padding: 12px;
    background: var(--el-bg-color);
    border-radius: 8px;
    border: 1px dashed var(--el-border-color-lighter);

    .priority-chain {
      display: flex;
      align-items: center;
      flex-wrap: wrap;
      gap: 8px;
    }

    .priority-step {
      display: flex;
      align-items: center;
      background: #fff;
      border: 1px solid var(--el-border-color);
      border-radius: 6px;
      padding: 4px 10px;
      font-size: 13px;
      font-weight: 600;
      color: var(--el-text-color-primary);

      .step-rank {
        display: flex;
        align-items: center;
        justify-content: center;
        width: 18px;
        height: 18px;
        background: var(--el-border-color-lighter);
        color: var(--el-text-color-secondary);
        border-radius: 4px;
        font-size: 11px;
        margin-right: 6px;
      }

      &.is-primary {
        border-color: var(--el-color-primary);
        background: var(--el-color-primary-light-9);
        color: var(--el-color-primary);
        .step-rank {
          background: var(--el-color-primary);
          color: #fff;
        }
      }
    }

    .chain-arrow { color: var(--el-text-color-placeholder); }
    .no-priority { font-size: 13px; color: #ef4444; }
  }

  .capability-section {
    margin-top: auto;

    .capability-list {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
    }

    .source-tag {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      padding: 4px 10px;
      border-radius: 16px;
      font-size: 12px;
      font-weight: 600;
      border: 1px solid transparent;

      &.full { background: #E4EFDF; color: #7CB342; border-color: #a7f3d0; }
      &.partial { background: #F9F2E3; color: #D4AF37; border-color: #fde68a; }
      &.none { background: var(--el-fill-color-lighter); color: var(--el-text-color-placeholder); border-color: var(--el-border-color-lighter); text-decoration: line-through; }
    }
  }
}

/* ── 图例说明 ── */
.legend-panel {
  margin-top: 10px;
  padding: 16px 20px;
  background: var(--el-fill-color-light);
  border-radius: 12px;
  
  .legend-title {
    display: flex;
    align-items: center;
    gap: 8px;
    font-weight: 600;
    margin-bottom: 12px;
    color: var(--el-text-color-regular);
  }

  .legend-items {
    display: flex;
    flex-wrap: wrap;
    gap: 24px;

    .legend-item {
      display: flex;
      align-items: center;
      gap: 10px;
      
      .legend-text { font-size: 13px; color: var(--el-text-color-secondary); }
    }
  }
}

/* ── 弹窗 ── */
.editor-header { margin-bottom: 20px; }
.editor-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.editor-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 16px;
  background: var(--el-bg-color);
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 8px;
  transition: all 0.2s;

  &:hover { background: #fff; border-color: var(--el-color-primary-light-5); box-shadow: 0 2px 8px rgba(0,0,0,0.05); }

  .editor-item-left {
    display: flex;
    align-items: center;
    
    .editor-rank {
      display: flex;
      align-items: center;
      justify-content: center;
      width: 24px;
      height: 24px;
      background: var(--el-border-color);
      color: #fff;
      border-radius: 6px;
      font-weight: 700;
      font-size: 12px;
      margin-right: 12px;

      &.is-first { background: var(--el-color-success); }
    }

    .editor-source { font-weight: 600; font-size: 15px; color: var(--el-text-color-primary); }
  }
}
</style>

