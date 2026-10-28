<template>
  <div class="knowledge-page">
    <!-- 页面头部 -->
    <div class="hero-header">
      <div class="hero-bg"></div>
      <div class="hero-content">
        <div class="hero-info">
          <h1 class="hero-title">
            <span class="hero-icon-wrap">
              <el-icon :size="28"><Collection /></el-icon>
            </span>
            知识库
          </h1>
          <p class="hero-subtitle">新闻语料向量化检索 — 分析师预注入与报告引用追溯</p>
        </div>
        <div class="embedding-chip" :class="{ off: !overview?.embedding?.configured }">
          <el-icon :size="14"><Cpu /></el-icon>
          <span v-if="overview?.embedding?.configured">
            {{ overview.embedding.provider }} / {{ overview.embedding.model_name }}
            <em v-if="overview.embedding.dimension">{{ overview.embedding.dimension }} 维</em>
          </span>
          <span v-else>未配置向量模型</span>
        </div>
      </div>
    </div>

    <el-tabs v-model="activeTab" class="kb-tabs" @tab-change="handleTabChange">
      <!-- ══════════ Tab 1: 语料概览 ══════════ -->
      <el-tab-pane label="语料概览" name="overview">
        <div v-if="loadingOverview" v-loading="true" class="kb-loading-block"></div>
        <template v-else>
          <el-alert
            v-if="!overview?.embedding?.configured"
            type="warning"
            :closable="false"
            show-icon
            class="kb-alert"
          >
            尚未配置向量模型。前往「系统设置 → 配置管理」添加 model_type=向量模型 的配置后，
            增量索引会自动开始（旧索引不兼容时自动全量重建）。
          </el-alert>

          <div class="market-grid">
            <div v-for="m in overview?.markets || []" :key="m.market" class="market-card">
              <div class="market-head">
                <span class="market-name">{{ marketLabel(m.market) }}</span>
                <el-tag :type="statusTagType(m.index_state?.status)" size="small" effect="light">
                  {{ statusLabel(m.index_state?.status) }}
                </el-tag>
              </div>
              <div class="market-stats">
                <div class="m-stat">
                  <div class="m-num">{{ formatNumber(m.corpus_count) }}</div>
                  <div class="m-desc">语料条数</div>
                </div>
                <div class="m-stat">
                  <div class="m-num">{{ formatNumber(m.indexed_count) }}</div>
                  <div class="m-desc">已索引</div>
                </div>
                <div class="m-stat">
                  <div class="m-num">{{ coveragePercent(m) }}%</div>
                  <div class="m-desc">覆盖率</div>
                </div>
              </div>
              <div class="market-foot">
                <span>最新语料：{{ m.latest_publish_time || '--' }}</span>
              </div>
            </div>
          </div>
        </template>
      </el-tab-pane>

      <!-- ══════════ Tab 2: 索引状态 ══════════ -->
      <el-tab-pane label="索引状态" name="index">
        <div v-if="loadingOverview" v-loading="true" class="kb-loading-block"></div>
        <template v-else>
          <div class="section-card">
            <div class="section-title">向量模型</div>
            <template v-if="overview?.embedding?.configured">
              <div class="kv-grid">
                <div class="kv"><span class="k">供应商</span><span class="v">{{ overview.embedding.provider || '--' }}</span></div>
                <div class="kv"><span class="k">模型</span><span class="v">{{ overview.embedding.model_name || '--' }}</span></div>
                <div class="kv"><span class="k">维度</span><span class="v">{{ overview.embedding.dimension || '模型默认' }}</span></div>
                <div class="kv"><span class="k">配置来源</span><span class="v">{{ overview.embedding.source || '--' }}</span></div>
              </div>
              <div class="kb-tip">
                切换向量模型或修改维度后，旧索引不兼容——下一轮增量索引会自动触发全量重建，也可手动执行。
              </div>
            </template>
            <el-empty v-else description="未配置向量模型" :image-size="60">
              <span class="empty-hint">在「系统设置 → 配置管理」添加模型类型为向量模型的配置</span>
            </el-empty>
          </div>

          <div class="section-card">
            <div class="section-title-row">
              <div class="section-title">各市场索引</div>
              <div class="action-row">
                <el-button size="small" :loading="actionLoading" @click="runIncremental">
                  <el-icon><RefreshRight /></el-icon>&nbsp;增量索引
                </el-button>
                <el-button size="small" type="danger" plain :loading="actionLoading" @click="confirmRebuild">
                  <el-icon><Delete /></el-icon>&nbsp;全量重建
                </el-button>
              </div>
            </div>
            <el-table :data="overview?.markets || []" size="default" class="kb-table">
              <el-table-column prop="market" label="市场" width="90">
                <template #default="{ row }">{{ marketLabel(row.market) }}</template>
              </el-table-column>
              <el-table-column label="状态" width="110">
                <template #default="{ row }">
                  <el-tag :type="statusTagType(row.index_state?.status)" size="small" effect="light">
                    {{ statusLabel(row.index_state?.status) }}
                  </el-tag>
                </template>
              </el-table-column>
              <el-table-column label="向量模型" min-width="180">
                <template #default="{ row }">
                  {{ row.index_state?.embedding_model || '--' }}
                  <span v-if="row.index_state?.dimension" class="dim-badge">{{ row.index_state.dimension }} 维</span>
                </template>
              </el-table-column>
              <el-table-column prop="corpus_count" label="语料" width="90">
                <template #default="{ row }">{{ formatNumber(row.corpus_count) }}</template>
              </el-table-column>
              <el-table-column prop="indexed_count" label="已索引" width="90">
                <template #default="{ row }">{{ formatNumber(row.indexed_count) }}</template>
              </el-table-column>
              <el-table-column label="最近运行" min-width="160">
                <template #default="{ row }">{{ formatTime(row.index_state?.last_run) }}</template>
              </el-table-column>
              <el-table-column label="错误" min-width="160">
                <template #default="{ row }">
                  <span v-if="row.index_state?.last_error" class="err-text">{{ row.index_state.last_error }}</span>
                  <span v-else class="ok-text">--</span>
                </template>
              </el-table-column>
            </el-table>
          </div>
        </template>
      </el-tab-pane>

      <!-- ══════════ Tab 3: 检索测试 ══════════ -->
      <el-tab-pane label="检索测试" name="search">
        <div class="section-card">
          <div class="section-title">语义检索</div>
          <el-form :model="searchForm" label-width="90px" class="search-form" @submit.prevent>
            <div class="search-grid">
              <el-form-item label="市场">
                <el-select v-model="searchForm.market" class="w-full">
                  <el-option label="A股 (CN)" value="CN" />
                  <el-option label="港股 (HK)" value="HK" />
                  <el-option label="美股 (US)" value="US" />
                </el-select>
              </el-form-item>
              <el-form-item label="股票代码">
                <el-input v-model="searchForm.symbol" placeholder="如 000001 / 00700 / AAPL" />
              </el-form-item>
              <el-form-item label="关键词" class="span-2">
                <el-input
                  v-model="searchForm.query"
                  placeholder="自然语言或关键词，如：业绩超预期 分红"
                  @keyup.enter="doSearch"
                />
              </el-form-item>
              <el-form-item label="截止日期">
                <el-date-picker
                  v-model="searchForm.as_of"
                  type="date"
                  value-format="YYYY-MM-DD"
                  placeholder="防前视截断（空=不限）"
                  class="w-full"
                />
              </el-form-item>
              <el-form-item label="起始日期">
                <el-date-picker
                  v-model="searchForm.start_date"
                  type="date"
                  value-format="YYYY-MM-DD"
                  placeholder="时间窗下界（可选）"
                  class="w-full"
                />
              </el-form-item>
              <el-form-item label="返回条数">
                <el-input-number v-model="searchForm.top_k" :min="1" :max="20" />
              </el-form-item>
              <el-form-item label=" ">
                <el-button type="primary" :loading="searching" @click="doSearch">检索</el-button>
              </el-form-item>
            </div>
          </el-form>
        </div>

        <div class="section-card" v-if="searched">
          <div class="section-title-row">
            <div class="section-title">检索结果（{{ searchResults.length }} 条）</div>
            <span v-if="searchForm.as_of" class="as-of-note">as_of = {{ searchForm.as_of }}（不含之后发布的语料）</span>
          </div>
          <el-empty v-if="!searching && searchResults.length === 0" description="无命中——检查索引是否就绪、代码是否正确" :image-size="60" />
          <div v-for="(r, i) in searchResults" :key="i" class="result-item">
            <div class="result-head">
              <span class="result-idx">{{ i + 1 }}</span>
              <span class="result-title">
                <a v-if="r.url" :href="r.url" target="_blank" rel="noopener noreferrer">{{ r.title }}</a>
                <template v-else>{{ r.title }}</template>
              </span>
              <span class="result-sim">相似度 {{ (r.similarity * 100).toFixed(1) }}%</span>
            </div>
            <div class="result-meta">
              <el-tag size="small" effect="plain" type="info">{{ r.type || 'news' }}</el-tag>
              <span>{{ r.data_source || '--' }}</span>
              <span>{{ r.publish_time || '--' }}</span>
              <span v-if="r.symbol">{{ r.symbol }}</span>
            </div>
            <div class="result-snippet">{{ r.snippet }}</div>
          </div>
        </div>
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<script setup lang="ts">
/**
 * 知识库页 — 三 tab：语料概览 / 索引状态 / 检索测试。
 *
 * 与「学习中心」的区别：学习中心是使用文档；本页是 stock_news 语料的
 * 向量索引运维与检索验证入口（对应后端 /api/knowledge/*）。
 */
import { onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Collection, Cpu, RefreshRight, Delete } from '@element-plus/icons-vue'
import { knowledgeApi, type KbOverview, type KbSearchResult } from '@/api/knowledge'

const route = useRoute()
const router = useRouter()

const VALID_TABS = ['overview', 'index', 'search'] as const
type KbTab = typeof VALID_TABS[number]

const activeTab = ref<KbTab>('overview')
const overview = ref<KbOverview | null>(null)
const loadingOverview = ref(false)
const actionLoading = ref(false)

const searchForm = reactive({
  market: 'CN',
  symbol: '',
  query: '',
  as_of: '',
  start_date: '',
  top_k: 6,
})
const searching = ref(false)
const searched = ref(false)
const searchResults = ref<KbSearchResult[]>([])

let pollTimer: ReturnType<typeof setInterval> | null = null

const marketLabel = (m: string) => ({ CN: 'A股', HK: '港股', US: '美股' } as Record<string, string>)[m] || m

const STATUS_META: Record<string, { label: string; type: 'success' | 'warning' | 'danger' | 'info' }> = {
  ready: { label: '就绪', type: 'success' },
  indexing: { label: '索引中', type: 'warning' },
  rebuilding: { label: '重建中', type: 'warning' },
  pending: { label: '待索引', type: 'info' },
  skipped: { label: '跳过', type: 'info' },
  error: { label: '错误', type: 'danger' },
}

const statusLabel = (s?: string | null) => STATUS_META[s || 'pending']?.label || s || '待索引'
const statusTagType = (s?: string | null) => STATUS_META[s || 'pending']?.type || 'info'

const formatNumber = (n?: number | null) =>
  typeof n === 'number' ? n.toLocaleString('zh-CN') : '--'

const formatTime = (iso?: string | null) => {
  if (!iso) return '--'
  return iso.replace('T', ' ').slice(0, 19)
}

const coveragePercent = (m: { corpus_count: number; indexed_count: number }) => {
  if (!m.corpus_count) return 0
  return Math.min(100, Math.round((m.indexed_count / m.corpus_count) * 100))
}

const loadOverview = async (showLoading = true) => {
  if (showLoading) loadingOverview.value = true
  try {
    overview.value = (await knowledgeApi.getOverview()).data
  } catch (e: any) {
    if (showLoading) ElMessage.error(e?.response?.data?.detail || '加载知识库概览失败')
  } finally {
    if (showLoading) loadingOverview.value = false
  }
}

// 索引中/重建中自动轮询进度；稳态不轮询
const syncPolling = () => {
  const busy = (overview.value?.markets || []).some(m =>
    ['indexing', 'rebuilding'].includes(m.index_state?.status || ''))
  if (busy && !pollTimer) {
    pollTimer = setInterval(() => loadOverview(false), 5000)
  } else if (!busy && pollTimer) {
    clearInterval(pollTimer)
    pollTimer = null
  }
}

const runIncremental = async () => {
  actionLoading.value = true
  try {
    const resp = await knowledgeApi.runIndex()
    ElMessage.success(resp.data?.message || '增量索引已提交后台执行')
    setTimeout(() => loadOverview(false), 1500)
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '触发增量索引失败（需管理员权限）')
  } finally {
    actionLoading.value = false
  }
}

const confirmRebuild = () => {
  ElMessageBox.confirm(
    '全量重建会清空并重扫所有市场的向量索引，语料量大时耗时较长。确定继续？',
    '全量重建索引',
    { confirmButtonText: '开始重建', cancelButtonText: '取消', type: 'warning' },
  ).then(async () => {
    actionLoading.value = true
    try {
      const resp = await knowledgeApi.rebuild()
      ElMessage.success(resp.data?.message || '重建已提交后台执行')
      await loadOverview(false)
    } catch (e: any) {
      ElMessage.error(e?.response?.data?.detail || '触发重建失败（需管理员权限）')
    } finally {
      actionLoading.value = false
    }
  }).catch(() => undefined)
}

const doSearch = async () => {
  if (!searchForm.symbol.trim() || !searchForm.query.trim()) {
    ElMessage.warning('请填写股票代码与检索关键词')
    return
  }
  searching.value = true
  searched.value = true
  try {
    const resp = await knowledgeApi.search({
      market: searchForm.market,
      symbol: searchForm.symbol.trim(),
      query: searchForm.query.trim(),
      as_of: searchForm.as_of || undefined,
      start_date: searchForm.start_date || undefined,
      top_k: searchForm.top_k,
    })
    searchResults.value = resp.data?.results || []
  } catch (e: any) {
    searchResults.value = []
    ElMessage.error(e?.response?.data?.detail || '检索失败')
  } finally {
    searching.value = false
  }
}

const handleTabChange = (tab: string | number) => {
  router.replace({ query: { ...route.query, tab: tab as string } })
}

watch(() => overview.value, syncPolling, { deep: true })

watch(
  () => route.query.tab,
  (tab) => {
    const next = VALID_TABS.includes(tab as KbTab) ? (tab as KbTab) : 'overview'
    if (next !== activeTab.value) activeTab.value = next
  },
)

onMounted(async () => {
  const tab = route.query.tab as KbTab
  if (VALID_TABS.includes(tab)) activeTab.value = tab
  await loadOverview()
  syncPolling()
})

onBeforeUnmount(() => {
  if (pollTimer) clearInterval(pollTimer)
})
</script>

<style lang="scss" scoped>
.knowledge-page {
  padding: 0 0 24px;
}

// ── 页头（与数据中心同构） ────────────────────────────────────────────────
.hero-header {
  position: relative;
  margin-bottom: 16px;
  border-radius: 12px;
  overflow: hidden;
  background: var(--el-bg-color);
  border: 1px solid var(--el-border-color-lighter);

  .hero-bg {
    position: absolute;
    inset: 0;
    background: linear-gradient(135deg, rgba(64, 158, 255, 0.08), transparent 55%);
    pointer-events: none;
  }

  .hero-content {
    position: relative;
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 16px;
    flex-wrap: wrap;
    padding: 20px 24px;
  }
}

.hero-info {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.hero-title {
  display: flex;
  align-items: center;
  gap: 10px;
  margin: 0;
  font-size: 22px;
  font-weight: 600;
  color: var(--el-text-color-primary);
}

.hero-icon-wrap {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 44px;
  height: 44px;
  border-radius: 10px;
  background: var(--el-color-primary-light-8);
  color: var(--el-color-primary);
}

.hero-subtitle {
  margin: 0 0 0 54px;
  font-size: 13px;
  color: var(--el-text-color-secondary);
}

.embedding-chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 6px 12px;
  border-radius: 999px;
  font-size: 13px;
  background: var(--el-color-success-light-9);
  color: var(--el-color-success);
  border: 1px solid var(--el-color-success-light-7);

  &.off {
    background: var(--el-color-warning-light-9);
    color: var(--el-color-warning);
    border-color: var(--el-color-warning-light-7);
  }

  em {
    font-style: normal;
    opacity: 0.8;
    margin-left: 4px;
  }
}

// ── tabs 与卡片 ───────────────────────────────────────────────────────────
.kb-tabs {
  :deep(.el-tabs__header) {
    margin-bottom: 16px;
  }
}

.kb-loading-block {
  min-height: 160px;
}

.kb-alert {
  margin-bottom: 16px;
}

.section-card {
  background: var(--el-bg-color);
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 10px;
  padding: 16px 20px;
  margin-bottom: 16px;
}

.section-title-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
  margin-bottom: 12px;
}

.section-title {
  font-size: 15px;
  font-weight: 600;
  color: var(--el-text-color-primary);
  margin-bottom: 12px;

  .section-title-row & {
    margin-bottom: 0;
  }
}

.action-row {
  display: flex;
  gap: 8px;
}

.kb-tip {
  margin-top: 12px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

.empty-hint {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

// ── 概览市场卡片 ─────────────────────────────────────────────────────────
.market-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
  gap: 16px;
}

.market-card {
  background: var(--el-bg-color);
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 10px;
  padding: 16px 20px;
}

.market-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 12px;
}

.market-name {
  font-size: 16px;
  font-weight: 600;
  color: var(--el-text-color-primary);
}

.market-stats {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 8px;
}

.m-stat {
  text-align: center;
  padding: 10px 4px;
  border-radius: 8px;
  background: var(--el-fill-color-light);
}

.m-num {
  font-size: 20px;
  font-weight: 600;
  color: var(--el-text-color-primary);
  font-variant-numeric: tabular-nums;
}

.m-desc {
  font-size: 12px;
  color: var(--el-text-color-secondary);
  margin-top: 2px;
}

.market-foot {
  margin-top: 12px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

// ── 键值网格 ──────────────────────────────────────────────────────────────
.kv-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
  gap: 10px 24px;
}

.kv {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  font-size: 13px;

  .k {
    color: var(--el-text-color-secondary);
  }

  .v {
    color: var(--el-text-color-primary);
    font-weight: 500;
    word-break: break-all;
    text-align: right;
  }
}

.dim-badge {
  margin-left: 6px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

.kb-table {
  width: 100%;
}

.err-text {
  color: var(--el-color-danger);
  font-size: 12px;
}

.ok-text {
  color: var(--el-text-color-placeholder);
}

// ── 检索测试 ──────────────────────────────────────────────────────────────
.search-form {
  .search-grid {
    display: grid;
    grid-template-columns: repeat(2, 1fr);
    gap: 0 24px;

    .span-2 {
      grid-column: span 2;
    }
  }

  .w-full {
    width: 100%;
  }
}

.as-of-note {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

.result-item {
  padding: 12px 0;
  border-bottom: 1px solid var(--el-border-color-lighter);

  &:last-child {
    border-bottom: none;
  }
}

.result-head {
  display: flex;
  align-items: baseline;
  gap: 8px;
}

.result-idx {
  flex-shrink: 0;
  min-width: 20px;
  height: 20px;
  line-height: 20px;
  text-align: center;
  border-radius: 4px;
  background: var(--el-color-primary-light-8);
  color: var(--el-color-primary);
  font-size: 12px;
  font-weight: 600;
}

.result-title {
  flex: 1;
  min-width: 0;
  font-weight: 500;
  color: var(--el-text-color-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;

  a {
    color: var(--el-color-primary);
    text-decoration: none;

    &:hover {
      text-decoration: underline;
    }
  }
}

.result-sim {
  flex-shrink: 0;
  font-size: 12px;
  color: var(--el-text-color-secondary);
  font-variant-numeric: tabular-nums;
}

.result-meta {
  display: flex;
  align-items: center;
  gap: 10px;
  margin: 6px 0 0 28px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

.result-snippet {
  margin: 6px 0 0 28px;
  font-size: 13px;
  color: var(--el-text-color-regular);
  line-height: 1.6;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

// ── 移动端 ────────────────────────────────────────────────────────────────
@media (max-width: 768px) {
  .hero-subtitle {
    margin-left: 0;
  }

  .search-form .search-grid {
    grid-template-columns: 1fr;

    .span-2 {
      grid-column: span 1;
    }
  }

  .search-form :deep(.el-form-item__label) {
    width: 76px !important;
  }
}
</style>
