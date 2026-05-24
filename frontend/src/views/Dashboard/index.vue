<template>
  <div class="dashboard">
    <!-- 搜索栏 -->
    <el-card class="search-card" shadow="hover">
      <div class="search-wrapper">
        <div class="search-icon">
          <el-icon :size="28"><Search /></el-icon>
        </div>
        <div class="search-body">
          <MarketSelector v-model="searchMarket" size="large" @change="searchStockCode = ''" />
          <el-input
            v-model="searchStockCode"
            :placeholder="searchPlaceholder"
            size="large"
            clearable
            class="search-input"
            @keyup.enter="handleQuickAnalysis"
          >
            <template #prefix>
              <el-icon><TrendCharts /></el-icon>
            </template>
          </el-input>
        </div>
        <el-button
          type="primary"
          size="large"
          class="search-btn"
          :disabled="!searchStockCode.trim()"
          @click="handleQuickAnalysis"
        >
          <el-icon><Promotion /></el-icon>
          快速分析
        </el-button>
      </div>
    </el-card>

    <!-- 数据概览卡片 -->
    <el-row :gutter="16" class="stat-row">
      <el-col :xs="12" :sm="12" :md="6">
        <div class="stat-card stat-card--blue" @click="router.push('/tasks')">
          <div class="stat-icon">
            <el-icon :size="24"><DataAnalysis /></el-icon>
          </div>
          <div class="stat-body">
            <div class="stat-value">{{ stats.todayAnalyses }}</div>
            <div class="stat-label">今日分析</div>
          </div>
        </div>
      </el-col>
      <el-col :xs="12" :sm="12" :md="6">
        <div class="stat-card stat-card--green">
          <div class="stat-icon">
            <el-icon :size="24"><SuccessFilled /></el-icon>
          </div>
          <div class="stat-body">
            <div class="stat-value">{{ stats.successRate }}%</div>
            <div class="stat-label">分析成功率</div>
          </div>
        </div>
      </el-col>
      <el-col :xs="12" :sm="12" :md="6">
        <div class="stat-card stat-card--orange" @click="router.push('/favorites')">
          <div class="stat-icon">
            <el-icon :size="24"><Star /></el-icon>
          </div>
          <div class="stat-body">
            <div class="stat-value">{{ stats.favoriteCount }}</div>
            <div class="stat-label">自选股</div>
          </div>
        </div>
      </el-col>
      <el-col :xs="12" :sm="12" :md="6">
        <div class="stat-card" :class="appStore.apiConnected ? 'stat-card--purple' : 'stat-card--red'">
          <div class="stat-icon">
            <el-icon :size="24"><Monitor /></el-icon>
          </div>
          <div class="stat-body">
            <div class="stat-value">{{ appStore.apiConnected ? '正常' : '异常' }}</div>
            <div class="stat-label">系统状态</div>
          </div>
        </div>
      </el-col>
    </el-row>

    <!-- 主内容区域：左右分栏 -->
    <el-row :gutter="20" class="main-content">
      <!-- 左侧 -->
      <el-col :xs="24" :lg="14">
        <!-- 最近分析 -->
        <el-card class="section-card" shadow="hover">
          <template #header>
            <div class="section-header">
              <span class="section-title">最近分析</span>
              <el-button type="primary" link @click="router.push('/tasks')">
                查看全部 <el-icon><ArrowRight /></el-icon>
              </el-button>
            </div>
          </template>
          <div v-if="recentTasks.length === 0" class="empty-state">
            <el-empty description="暂无分析记录" :image-size="64">
              <el-button type="primary" @click="router.push('/analysis/single')">
                开始第一次分析
              </el-button>
            </el-empty>
          </div>
          <div v-else class="task-list">
            <div
              v-for="task in recentTasks"
              :key="task.task_id"
              class="task-item"
              @click="viewTask(task)"
            >
              <div class="task-left">
                <div class="task-symbol">{{ task.symbol || task.stock_code || '-' }}</div>
                <div class="task-name">{{ task.stock_name || '-' }}</div>
              </div>
              <div class="task-center">
                <el-tag :type="getStatusType(task.status)" size="small" effect="light">
                  {{ getStatusText(task.status) }}
                </el-tag>
              </div>
              <div class="task-right">
                <span class="task-time">{{ formatRelativeTime(task.created_at) }}</span>
                <el-icon class="task-arrow"><ArrowRight /></el-icon>
              </div>
            </div>
          </div>
        </el-card>

        <!-- 快捷入口 -->
        <el-card class="section-card shortcuts-card" shadow="hover">
          <template #header>
            <div class="section-header">
              <span class="section-title">快捷入口</span>
            </div>
          </template>
          <el-row :gutter="12">
            <el-col :span="8" v-for="item in shortcuts" :key="item.path">
              <div class="shortcut-item" @click="router.push(item.path)">
                <div class="shortcut-icon" :style="{ backgroundColor: item.bgColor, color: item.iconColor }">
                  <el-icon :size="22"><component :is="item.icon" /></el-icon>
                </div>
                <div class="shortcut-label">{{ item.label }}</div>
              </div>
            </el-col>
          </el-row>
        </el-card>

        <!-- 市场动态 -->
        <el-card class="section-card" shadow="hover">
          <template #header>
            <div class="section-header">
              <span class="section-title">市场动态</span>
            </div>
          </template>
          <div v-if="marketNews.length === 0" class="empty-state-sm">
            <span class="empty-text">暂无市场快讯</span>
          </div>
          <div v-else class="news-list">
            <div
              v-for="news in marketNews"
              :key="news.id"
              class="news-item"
              @click="openNewsUrl(news.url)"
            >
              <div class="news-title">{{ news.title }}</div>
              <div class="news-meta">
                <el-tag v-if="news.source" size="small" type="info" effect="plain">{{ news.source }}</el-tag>
                <span class="news-time">{{ formatRelativeTime(news.time) }}</span>
              </div>
            </div>
          </div>
        </el-card>
      </el-col>

      <!-- 右侧 -->
      <el-col :xs="24" :lg="10">
        <!-- 自选股行情 -->
        <el-card class="section-card" shadow="hover">
          <template #header>
            <div class="section-header">
              <span class="section-title">自选股行情</span>
              <el-button type="primary" link @click="router.push('/favorites')">
                查看全部 <el-icon><ArrowRight /></el-icon>
              </el-button>
            </div>
          </template>
          <div v-if="favoriteStocks.length === 0" class="empty-state-sm">
            <el-empty description="暂无自选股" :image-size="48">
              <el-button type="primary" size="small" @click="router.push('/favorites')">
                添加自选股
              </el-button>
            </el-empty>
          </div>
          <div v-else class="fav-list">
            <div
              v-for="stock in favoriteStocks.slice(0, 5)"
              :key="stock.stock_code || stock.symbol"
              class="fav-item"
              @click="goToAnalysis(stock)"
            >
              <div class="fav-info">
                <div class="fav-code">{{ stock.stock_code || stock.symbol }}</div>
                <div class="fav-name">{{ stock.stock_name }}</div>
              </div>
              <div class="fav-price">
                <div class="fav-current">{{ stock.current_price ? `¥${stock.current_price}` : '-' }}</div>
                <div class="fav-change" :class="getPriceClass(stock.change_percent)">
                  {{ formatChangePercent(stock.change_percent) }}
                </div>
              </div>
            </div>
            <div v-if="favoriteStocks.length > 5" class="fav-more">
              <el-button type="primary" link size="small" @click="router.push('/favorites')">
                查看全部 {{ favoriteStocks.length }} 只
              </el-button>
            </div>
          </div>
        </el-card>

        <!-- 数据源同步 -->
        <div class="sync-card-wrapper">
          <MultiSourceSyncCard />
        </div>
      </el-col>
    </el-row>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import {
  Search,
  TrendCharts,
  Promotion,
  DataAnalysis,
  SuccessFilled,
  Star,
  Monitor,
  ArrowRight,
  Document,
  Files,
  List,
  Reading
} from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import MarketSelector from '@/components/Global/MarketSelector.vue'
import MultiSourceSyncCard from '@/components/Dashboard/MultiSourceSyncCard.vue'
import { useAppStore } from '@/stores/app'
import { analysisApi } from '@/api/analysis'
import { favoritesApi } from '@/api/favorites'
import { newsApi } from '@/api/news'
import { formatRelativeTime } from '@/utils/datetime'
import type { AnalysisStatus } from '@/types/analysis'

const router = useRouter()
const appStore = useAppStore()

// ==================== 搜索栏 ====================
const searchMarket = ref('CN')
const searchStockCode = ref('')

const searchPlaceholder = computed(() => {
  const map: Record<string, string> = {
    CN: '输入 A 股代码或名称，如 000001、平安银行',
    HK: '输入港股代码或名称，如 00700、腾讯',
    US: '输入美股代码或名称，如 AAPL、苹果',
  }
  return map[searchMarket.value] || '输入股票代码或名称'
})

const handleQuickAnalysis = () => {
  const code = searchStockCode.value.trim()
  if (!code) return
  router.push({ path: '/analysis/single', query: { stock_code: code, market: searchMarket.value } })
}

// ==================== 数据概览 ====================
const stats = ref({
  todayAnalyses: 0,
  successRate: 0,
  favoriteCount: 0,
})

const loadStats = async () => {
  try {
    // 获取今日分析统计
    const today = new Date().toISOString().slice(0, 10)
    const res = await analysisApi.getAnalysisStats({ start_date: today, end_date: today })
    const data = (res as any)?.data?.data || (res as any)?.data || {}
    stats.value.todayAnalyses = data.total_analyses ?? data.daily_analyses ?? 0
    const total = data.total_analyses ?? 0
    const success = data.successful_analyses ?? 0
    stats.value.successRate = total > 0 ? Math.round((success / total) * 100) : 0
  } catch (err) {
    console.error('加载分析统计失败:', err)
  }

  try {
    const favRes = await favoritesApi.list()
    if (favRes.success && favRes.data) {
      stats.value.favoriteCount = favRes.data.length
    }
  } catch (err) {
    console.error('加载自选股数量失败:', err)
  }
}

// ==================== 最近分析 ====================
const recentTasks = ref<any[]>([])

const loadRecentTasks = async () => {
  try {
    const res = await analysisApi.getTaskList({ limit: 5, offset: 0 })
    const body = (res as any)?.data?.data || (res as any)?.data || res || {}
    recentTasks.value = body.tasks || []
  } catch (err) {
    console.error('加载最近分析失败:', err)
    recentTasks.value = []
  }
}

const getStatusType = (status: string | AnalysisStatus): 'success' | 'info' | 'warning' | 'danger' => {
  const map: Record<string, 'success' | 'info' | 'warning' | 'danger'> = {
    pending: 'info',
    processing: 'warning',
    running: 'warning',
    completed: 'success',
    failed: 'danger',
    cancelled: 'info',
  }
  return map[status] || 'info'
}

const getStatusText = (status: string | AnalysisStatus) => {
  const map: Record<string, string> = {
    pending: '等待中',
    processing: '分析中',
    running: '分析中',
    completed: '已完成',
    failed: '失败',
    cancelled: '已取消',
  }
  return map[status] || String(status)
}

const viewTask = (task: any) => {
  if (task.status === 'completed') {
    router.push({ name: 'ReportDetail', params: { id: task.task_id } })
  } else {
    router.push('/tasks?tab=running')
  }
}

// ==================== 自选股 ====================
const favoriteStocks = ref<any[]>([])

const loadFavoriteStocks = async () => {
  try {
    const response = await favoritesApi.list()
    if (response.success && response.data) {
      favoriteStocks.value = response.data.map((item: any) => ({
        stock_code: item.stock_code || item.symbol,
        symbol: item.symbol,
        stock_name: item.stock_name,
        current_price: item.current_price || 0,
        change_percent: item.change_percent || 0,
      }))
    }
  } catch (err) {
    console.error('加载自选股失败:', err)
  }
}

const goToAnalysis = (stock: any) => {
  const code = stock.stock_code || stock.symbol || ''
  router.push(`/analysis/single?stock_code=${code}`)
}

const getPriceClass = (pct: number) => {
  if (pct > 0) return 'price-up'
  if (pct < 0) return 'price-down'
  return 'price-flat'
}

const formatChangePercent = (pct: number | null | undefined) => {
  if (pct == null) return '-'
  const sign = pct > 0 ? '+' : ''
  return `${sign}${Number(pct).toFixed(2)}%`
}

// ==================== 市场动态 ====================
const marketNews = ref<any[]>([])

const loadMarketNews = async () => {
  try {
    let response = await newsApi.getLatestNews(undefined, 5, 24)
    if (response.success && response.data && response.data.news.length === 0) {
      response = await newsApi.getLatestNews(undefined, 5, 24 * 30)
    }
    if (response.success && response.data) {
      marketNews.value = response.data.news.map((item: any) => ({
        id: item.id || item.title,
        title: item.title,
        time: item.publish_time,
        url: item.url,
        source: item.source,
      }))
    }
  } catch (err) {
    console.error('加载市场快讯失败:', err)
    marketNews.value = []
  }
}

const openNewsUrl = (url?: string) => {
  if (url) {
    window.open(url, '_blank')
  } else {
    ElMessage.info('该新闻暂无详情链接')
  }
}

// ==================== 快捷入口 ====================
const shortcuts = [
  { label: '单股分析', path: '/analysis/single', icon: TrendCharts, bgColor: 'var(--el-color-primary-light-9)', iconColor: 'var(--el-color-primary)' },
  { label: '批量分析', path: '/analysis/batch', icon: Files, bgColor: 'var(--el-color-warning-light-9)', iconColor: 'var(--el-color-warning)' },
  { label: '股票筛选', path: '/screening', icon: Search, bgColor: 'var(--el-color-success-light-9)', iconColor: 'var(--el-color-success)' },
  { label: '分析报告', path: '/reports', icon: Document, bgColor: 'var(--el-color-danger-light-9)', iconColor: 'var(--el-color-danger)' },
  { label: '任务中心', path: '/tasks', icon: List, bgColor: 'var(--el-fill-color)', iconColor: 'var(--el-text-color-secondary)' },
  { label: '学习中心', path: '/learning', icon: Reading, bgColor: 'var(--el-color-primary-light-9)', iconColor: '#C5A55A' },
]

// ==================== 生命周期 ====================
onMounted(async () => {
  appStore.checkApiConnection()
  await Promise.all([
    loadStats(),
    loadRecentTasks(),
    loadFavoriteStocks(),
    loadMarketNews(),
  ])
})
</script>

<style lang="scss" scoped>
.dashboard {
  max-width: 1400px;
  margin: 0 auto;
}

/* ========== 搜索栏 ========== */
.search-card {
  margin-bottom: 20px;
  border-radius: 12px;

  :deep(.el-card__body) {
    padding: 20px 24px;
  }
}

.search-wrapper {
  display: flex;
  align-items: center;
  gap: 16px;
}

.search-icon {
  flex-shrink: 0;
  width: 48px;
  height: 48px;
  border-radius: 12px;
  background: linear-gradient(135deg, var(--el-color-primary), var(--el-color-primary-light-3));
  display: flex;
  align-items: center;
  justify-content: center;
  color: #fff;
}

.search-body {
  flex: 1;
  display: flex;
  align-items: center;
  gap: 12px;

  .search-input {
    flex: 1;
  }
}

.search-btn {
  flex-shrink: 0;
  height: 40px;
  padding: 0 24px;
  border-radius: 8px;
  font-size: 15px;
  font-weight: 500;
}

/* ========== 数据概览卡片 ========== */
.stat-row {
  margin-bottom: 20px;
}

.stat-card {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 20px;
  border-radius: 12px;
  background: var(--el-bg-color);
  border: 1px solid var(--el-border-color-lighter);
  cursor: pointer;
  transition: all 0.25s ease;

  &:hover {
    transform: translateY(-2px);
    box-shadow: 0 4px 16px rgba(0, 0, 0, 0.08);
  }

  .stat-icon {
    flex-shrink: 0;
    width: 48px;
    height: 48px;
    border-radius: 12px;
    display: flex;
    align-items: center;
    justify-content: center;
  }

  .stat-body {
    .stat-value {
      font-size: 24px;
      font-weight: 700;
      line-height: 1.2;
      font-variant-numeric: tabular-nums;
    }

    .stat-label {
      font-size: 13px;
      color: var(--el-text-color-secondary);
      margin-top: 2px;
    }
  }

  &--blue {
    border-left: 4px solid var(--el-color-primary);
    .stat-icon { background: var(--el-color-primary-light-9); color: var(--el-color-primary); }
    .stat-value { color: var(--el-color-primary); }
  }

  &--green {
    border-left: 4px solid var(--el-color-success);
    .stat-icon { background: var(--el-color-success-light-9); color: var(--el-color-success); }
    .stat-value { color: var(--el-color-success); }
  }

  &--orange {
    border-left: 4px solid var(--el-color-warning);
    .stat-icon { background: var(--el-color-warning-light-9); color: var(--el-color-warning); }
    .stat-value { color: var(--el-color-warning); }
  }

  &--purple {
    border-left: 4px solid #C5A55A;
    .stat-icon { background: var(--el-color-primary-light-9); color: #C5A55A; }
    .stat-value { color: #C5A55A; }
  }

  &--red {
    border-left: 4px solid var(--el-color-danger);
    .stat-icon { background: var(--el-color-danger-light-9); color: var(--el-color-danger); }
    .stat-value { color: var(--el-color-danger); }
  }
}

/* ========== 通用 section ========== */
.section-card {
  margin-bottom: 20px;
  border-radius: 12px;

  :deep(.el-card__header) {
    padding: 16px 20px;
    border-bottom: 1px solid var(--el-border-color-lighter);
  }

  :deep(.el-card__body) {
    padding: 16px 20px;
  }
}

.section-header {
  display: flex;
  align-items: center;
  justify-content: space-between;

  .section-title {
    font-size: 16px;
    font-weight: 600;
    color: var(--el-text-color-primary);
  }
}

.empty-state {
  padding: 24px 0;
  text-align: center;
}

.empty-state-sm {
  padding: 16px 0;
  text-align: center;

  .empty-text {
    font-size: 13px;
    color: var(--el-text-color-placeholder);
  }
}

/* ========== 最近分析 ========== */
.task-list {
  .task-item {
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 12px 0;
    border-bottom: 1px solid var(--el-border-color-extra-light);
    cursor: pointer;
    transition: background-color 0.2s;

    &:last-child {
      border-bottom: none;
    }

    &:hover {
      background: var(--el-fill-color-lighter);
      margin: 0 -20px;
      padding: 12px 20px;
      border-radius: 8px;
    }

    .task-left {
      flex: 1;
      min-width: 0;

      .task-symbol {
        font-size: 14px;
        font-weight: 600;
        color: var(--el-text-color-primary);
      }

      .task-name {
        font-size: 12px;
        color: var(--el-text-color-secondary);
        margin-top: 2px;
      }
    }

    .task-center {
      flex-shrink: 0;
    }

    .task-right {
      flex-shrink: 0;
      display: flex;
      align-items: center;
      gap: 4px;

      .task-time {
        font-size: 12px;
        color: var(--el-text-color-placeholder);
      }

      .task-arrow {
        font-size: 12px;
        color: var(--el-text-color-placeholder);
        transition: transform 0.2s;
      }
    }

    &:hover .task-right .task-arrow {
      transform: translateX(2px);
    }
  }
}

/* ========== 快捷入口 ========== */
.shortcuts-card {
  :deep(.el-card__body) {
    padding: 20px;
  }
}

.shortcut-item {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 10px;
  padding: 16px 8px;
  border-radius: 12px;
  cursor: pointer;
  transition: all 0.25s ease;

  &:hover {
    transform: translateY(-2px);
    background: var(--el-fill-color-lighter);
  }

  .shortcut-icon {
    width: 48px;
    height: 48px;
    border-radius: 12px;
    display: flex;
    align-items: center;
    justify-content: center;
    transition: transform 0.25s ease;
  }

  &:hover .shortcut-icon {
    transform: scale(1.08);
  }

  .shortcut-label {
    font-size: 13px;
    font-weight: 500;
    color: var(--el-text-color-primary);
    text-align: center;
  }
}

/* ========== 市场动态 ========== */
.news-list {
  .news-item {
    padding: 10px 0;
    border-bottom: 1px solid var(--el-border-color-extra-light);
    cursor: pointer;
    transition: background-color 0.2s;

    &:last-child {
      border-bottom: none;
    }

    &:hover {
      background: var(--el-fill-color-lighter);
      margin: 0 -20px;
      padding: 10px 20px;
      border-radius: 6px;
    }

    .news-title {
      font-size: 14px;
      color: var(--el-text-color-primary);
      line-height: 1.5;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }

    .news-meta {
      display: flex;
      align-items: center;
      gap: 8px;
      margin-top: 4px;

      .news-time {
        font-size: 12px;
        color: var(--el-text-color-placeholder);
      }
    }
  }
}

/* ========== 自选股行情 ========== */
.fav-list {
  .fav-item {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 10px 0;
    border-bottom: 1px solid var(--el-border-color-extra-light);
    cursor: pointer;
    transition: background-color 0.2s;

    &:last-child {
      border-bottom: none;
    }

    &:hover {
      background: var(--el-fill-color-lighter);
      margin: 0 -20px;
      padding: 10px 20px;
      border-radius: 6px;
    }

    .fav-info {
      .fav-code {
        font-size: 14px;
        font-weight: 600;
        color: var(--el-text-color-primary);
      }

      .fav-name {
        font-size: 12px;
        color: var(--el-text-color-secondary);
        margin-top: 2px;
      }
    }

    .fav-price {
      text-align: right;

      .fav-current {
        font-size: 14px;
        font-weight: 600;
        color: var(--el-text-color-primary);
      }

      .fav-change {
        font-size: 12px;
        margin-top: 2px;
        font-weight: 500;

        &.price-up { color: #E57373; }
        &.price-down { color: #7CB342; }
        &.price-flat { color: var(--el-text-color-secondary); }
      }
    }
  }

  .fav-more {
    text-align: center;
    padding-top: 8px;
    margin-top: 4px;
    border-top: 1px solid var(--el-border-color-lighter);
  }
}

/* ========== 数据源同步 ========== */
.sync-card-wrapper {
  margin-bottom: 20px;
}

/* ========== 响应式 ========== */
@media (max-width: 768px) {
  .search-wrapper {
    flex-direction: column;
    gap: 12px;
  }

  .search-icon {
    display: none;
  }

  .search-body {
    flex-direction: column;
    width: 100%;
  }

  .search-btn {
    width: 100%;
  }

  .stat-card {
    padding: 16px;

    .stat-body .stat-value {
      font-size: 20px;
    }
  }

  .main-content {
    .el-col {
      margin-bottom: 0;
    }
  }
}
</style>
