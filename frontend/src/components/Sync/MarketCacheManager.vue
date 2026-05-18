<template>
  <div class="market-cache-manager">
    <!-- 缓存统计 -->
    <el-card shadow="hover" class="stats-card">
      <template #header>
        <div class="card-header">
          <el-icon class="header-icon"><DataLine /></el-icon>
          <span class="header-title">{{ marketLabel }}缓存管理</span>
        </div>
      </template>

      <div v-if="stats" class="stats-grid">
        <div class="stat-item">
          <div class="stat-value">{{ stats.cached_symbols ?? 0 }}</div>
          <div class="stat-label">已缓存股票</div>
        </div>
        <div class="stat-item">
          <div class="stat-value success">{{ stats.valid_documents ?? 0 }}</div>
          <div class="stat-label">有效缓存</div>
        </div>
        <div class="stat-item">
          <div class="stat-value danger">{{ stats.expired_documents ?? 0 }}</div>
          <div class="stat-label">已过期</div>
        </div>
        <div class="stat-item">
          <div class="stat-value info">{{ stats.cache_hours ?? 24 }}h</div>
          <div class="stat-label">缓存时长</div>
        </div>
      </div>

      <div v-if="stats?.last_updated" class="last-update">
        最后更新: {{ formatTime(stats.last_updated) }}
      </div>
    </el-card>

    <!-- 单股搜索预热 -->
    <el-card shadow="hover" class="warm-card">
      <template #header>
        <div class="card-header">
          <el-icon class="header-icon"><Search /></el-icon>
          <span class="header-title">缓存预热</span>
        </div>
      </template>

      <div class="warm-section">
        <div class="warm-input-row">
          <el-input
            v-model="warmSymbol"
            :placeholder="market === 'HK' ? '输入港股代码，如 00700' : '输入美股代码，如 AAPL'"
            clearable
            @keyup.enter="handleWarmSingle"
          >
            <template #append>
              <el-button :loading="warmingSingle" @click="handleWarmSingle">
                预热缓存
              </el-button>
            </template>
          </el-input>
        </div>

        <!-- 预热结果 -->
        <div v-if="warmResult" class="warm-result">
          <el-alert
            :title="warmResult.info_success ? '预热成功' : '预热失败'"
            :type="warmResult.info_success ? 'success' : 'error'"
            :closable="true"
            show-icon
            @close="warmResult = null"
          >
            <template v-if="warmResult.info_success">
              基础信息已缓存，行情数据 {{ warmResult.quotes_count }} 条（来源: {{ warmResult.source }}）
            </template>
          </el-alert>
        </div>

        <!-- 批量预热：自选股 -->
        <el-divider content-position="left">批量预热</el-divider>

        <div class="batch-actions">
          <el-button
            type="primary"
            :loading="batchWarming"
            @click="handleWarmFavorites"
          >
            <el-icon><Star /></el-icon>
            预热{{ marketLabel }}自选股
          </el-button>
          <el-button
            type="danger"
            plain
            size="small"
            @click="handleClearCache"
          >
            清理过期缓存
          </el-button>
        </div>

        <!-- 批量预热进度 -->
        <div v-if="batchStatus && batchStatus.status !== 'idle'" class="batch-progress">
          <div class="progress-header">
            <el-tag :type="batchStatus.status === 'running' ? 'warning' : batchStatus.status === 'completed' ? 'success' : 'info'">
              {{ batchStatus.status === 'running' ? '预热中' : '已完成' }}
            </el-tag>
            <span class="progress-text">
              {{ batchStatus.completed }} / {{ batchStatus.total }}
              <span v-if="batchStatus.failed > 0" class="failed-count">（{{ batchStatus.failed }} 失败）</span>
            </span>
          </div>
          <el-progress
            :percentage="batchStatus.total > 0 ? Math.round(batchStatus.completed / batchStatus.total * 100) : 0"
            :status="batchStatus.failed > 0 ? 'warning' : 'success'"
            :stroke-width="8"
          />

          <!-- 每股结果列表 -->
          <div v-if="batchStatus.results?.length" class="batch-results">
            <div
              v-for="(item, idx) in batchStatus.results"
              :key="idx"
              class="batch-result-item"
            >
              <el-tag :type="item.success ? 'success' : 'danger'" size="small">
                {{ item.symbol }}
              </el-tag>
              <span class="batch-result-msg">{{ item.message }}</span>
            </div>
          </div>
        </div>
      </div>
    </el-card>

    <!-- 已缓存股票列表 -->
    <el-card shadow="hover" class="list-card">
      <template #header>
        <div class="card-header">
          <el-icon class="header-icon"><List /></el-icon>
          <span class="header-title">已缓存股票</span>
          <el-button
            size="small"
            :loading="listLoading"
            @click="fetchCachedList()"
          >
            刷新
          </el-button>
        </div>
      </template>

      <div v-loading="listLoading">
        <el-table
          v-if="cachedList.length"
          :data="cachedList"
          stripe
          size="small"
          style="width: 100%"
        >
          <el-table-column prop="symbol" label="代码" width="120" />
          <el-table-column prop="name" label="名称" min-width="140">
            <template #default="{ row }">
              {{ row.name || '-' }}
            </template>
          </el-table-column>
          <el-table-column prop="data_source" label="数据源" width="120">
            <template #default="{ row }">
              <el-tag size="small" type="info">{{ row.data_source }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="updated_at" label="缓存时间" width="180">
            <template #default="{ row }">
              {{ formatTime(row.updated_at) }}
            </template>
          </el-table-column>
          <el-table-column label="操作" width="100" fixed="right">
            <template #default="{ row }">
              <el-button
                size="small"
                type="primary"
                link
                :loading="refreshingSymbol === row.symbol"
                @click="handleRefreshSingle(row.symbol)"
              >
                刷新
              </el-button>
            </template>
          </el-table-column>
        </el-table>

        <div v-if="!listLoading && !cachedList.length" class="empty-state">
          <el-empty description="暂无缓存数据" :image-size="60" />
        </div>

        <div v-if="cachedList.length && hasMore" class="load-more">
          <el-button size="small" text @click="loadMore">加载更多</el-button>
        </div>
      </div>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { DataLine, Search, Star, List } from '@element-plus/icons-vue'
import {
  getMarketCacheStats,
  warmMarketCache,
  warmMarketCacheBatch,
  getMarketCacheWarmStatus,
  clearMarketCache,
  getMarketCacheList,
  type MarketCacheStats,
  type MarketType,
} from '@/api/sync'
import { favoritesApi } from '@/api/favorites'

interface Props {
  market: MarketType
}

const props = defineProps<Props>()

const marketLabel = computed(() => props.market === 'HK' ? '港股' : '美股')

// 统计
const stats = ref<MarketCacheStats | null>(null)

// 单股预热
const warmSymbol = ref('')
const warmingSingle = ref(false)
const warmResult = ref<{ symbol: string; info_success: boolean; quotes_count: number; source: string } | null>(null)

// 批量预热
const batchWarming = ref(false)
const batchStatus = ref<{ status: string; total: number; completed: number; failed: number; results: Array<{ symbol: string; success: boolean; message: string }> } | null>(null)
let batchPollTimer: ReturnType<typeof setInterval> | null = null

// 缓存列表
const listLoading = ref(false)
const cachedList = ref<Array<{ symbol: string; name?: string; data_source: string; updated_at: string }>>([])
const listPage = ref(1)
const hasMore = ref(false)
const refreshingSymbol = ref('')

const formatTime = (isoString: string) => {
  if (!isoString) return '-'
  try {
    const date = new Date(isoString)
    return date.toLocaleString('zh-CN', {
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
    })
  } catch {
    return isoString
  }
}

// 获取统计
const fetchStats = async () => {
  try {
    const res = await getMarketCacheStats(props.market)
    if (res.success) {
      stats.value = res.data
    }
  } catch (e: any) {
    console.error('获取缓存统计失败:', e)
  }
}

// 获取缓存列表
const fetchCachedList = async (page = 1) => {
  try {
    listLoading.value = true
    const res = await getMarketCacheList(props.market, page, 20)
    if (res.success) {
      if (page === 1) {
        cachedList.value = res.data.records || []
      } else {
        cachedList.value.push(...(res.data.records || []))
      }
      listPage.value = page
      hasMore.value = res.data.has_more
    }
  } catch (e: any) {
    console.error('获取缓存列表失败:', e)
  } finally {
    listLoading.value = false
  }
}

const loadMore = () => {
  fetchCachedList(listPage.value + 1)
}

// 单股预热
const handleWarmSingle = async () => {
  if (!warmSymbol.value.trim()) {
    ElMessage.warning(marketLabel.value === '港股' ? '请输入港股代码' : '请输入美股代码')
    return
  }
  warmingSingle.value = true
  warmResult.value = null
  try {
    const res = await warmMarketCache(props.market, warmSymbol.value.trim())
    if (res.success && res.data?.info_success) {
      warmResult.value = res.data
      ElMessage.success(res.message || '预热成功')
      await fetchStats()
      fetchCachedList(1)
    } else {
      warmResult.value = res.data || { symbol: warmSymbol.value, info_success: false, quotes_count: 0, source: '' }
      ElMessage.error(res.message || '预热失败')
    }
  } catch (e: any) {
    ElMessage.error(`预热失败: ${e.message}`)
  } finally {
    warmingSingle.value = false
  }
}

// 刷新单股
const handleRefreshSingle = async (symbol: string) => {
  refreshingSymbol.value = symbol
  try {
    const res = await warmMarketCache(props.market, symbol, true)
    if (res.success) {
      ElMessage.success(`${symbol} 缓存已刷新`)
      await fetchCachedList(1)
    } else {
      ElMessage.error(`刷新失败: ${res.message}`)
    }
  } catch (e: any) {
    ElMessage.error(`刷新失败: ${e.message}`)
  } finally {
    refreshingSymbol.value = ''
  }
}

// 自选股批量预热
const handleWarmFavorites = async () => {
  try {
    batchWarming.value = true
    const favRes = await favoritesApi.list()
    if (!favRes.success || !favRes.data?.length) {
      ElMessage.warning('暂无自选股')
      batchWarming.value = false
      return
    }

    const marketFilter = props.market === 'HK' ? '港股' : '美股'
    const symbols = favRes.data
      .filter((f: any) => f.market === marketFilter || f.market === props.market)
      .map((f: any) => f.symbol || f.stock_code)
      .filter(Boolean)

    if (!symbols.length) {
      ElMessage.warning(`暂无${marketLabel.value}自选股`)
      batchWarming.value = false
      return
    }

    const batchRes = await warmMarketCacheBatch(props.market, symbols)
    if (batchRes.success) {
      ElMessage.success(`批量预热已启动，共 ${batchRes.data.total} 只股票`)
      startBatchPoll()
    } else {
      ElMessage.error(`批量预热失败: ${batchRes.message}`)
    }
  } catch (e: any) {
    // 401 由全局拦截器处理（跳转登录页），不再重复弹消息
    if (e?.response?.status !== 401) {
      ElMessage.error(`批量预热失败: ${e.message}`)
    }
  } finally {
    batchWarming.value = false
  }
}

// 批量预热轮询
const startBatchPoll = () => {
  stopBatchPoll()
  batchPollTimer = setInterval(async () => {
    try {
      const res = await getMarketCacheWarmStatus(props.market)
      if (res.success) {
        batchStatus.value = {
          status: res.data.status,
          total: res.data.total,
          completed: res.data.completed,
          failed: res.data.failed,
          results: res.data.results || [],
        }
        if (res.data.status === 'completed' || res.data.status === 'idle') {
          stopBatchPoll()
          if (res.data.status === 'completed') {
            await fetchStats()
            fetchCachedList(1)
            const failedCount = res.data.failed
            if (failedCount > 0) {
              ElMessage.warning(`批量预热完成，成功 ${res.data.total - failedCount}/${res.data.total}`)
            } else {
              ElMessage.success(`批量预热完成，全部 ${res.data.total} 只股票预热成功`)
            }
          }
        }
      }
    } catch {
      stopBatchPoll()
    }
  }, 3000)
}

const stopBatchPoll = () => {
  if (batchPollTimer) {
    clearInterval(batchPollTimer)
    batchPollTimer = null
  }
}

// 清理缓存
const handleClearCache = async () => {
  try {
    await ElMessageBox.confirm(
      '确定要清理过期缓存吗？',
      '确认清理',
      { confirmButtonText: '确定', cancelButtonText: '取消', type: 'warning' },
    )
    const res = await clearMarketCache(props.market)
    if (res.success) {
      ElMessage.success(res.message || '缓存清理完成')
      await fetchStats()
      fetchCachedList(1)
    } else {
      ElMessage.error(`清理失败: ${res.message}`)
    }
  } catch {
    // 用户取消
  }
}

onMounted(async () => {
  await Promise.all([fetchStats(), fetchCachedList(1)])
  // 恢复可能正在运行的批量预热任务
  try {
    const statusRes = await getMarketCacheWarmStatus(props.market)
    if (statusRes.success && statusRes.data?.status === 'running') {
      batchStatus.value = {
        status: statusRes.data.status,
        total: statusRes.data.total,
        completed: statusRes.data.completed,
        failed: statusRes.data.failed,
        results: statusRes.data.results || [],
      }
      startBatchPoll()
    }
  } catch {
    // 忽略，不影响正常使用
  }
})

onUnmounted(() => {
  stopBatchPoll()
})

watch(() => props.market, async () => {
  warmSymbol.value = ''
  warmResult.value = null
  batchStatus.value = null
  stopBatchPoll()
  await Promise.all([fetchStats(), fetchCachedList(1)])
})
</script>

<style scoped lang="scss">
.market-cache-manager {
  display: flex;
  flex-direction: column;
  gap: 16px;

  .card-header {
    display: flex;
    align-items: center;

    .header-icon {
      margin-right: 8px;
      color: var(--el-color-primary);
    }

    .header-title {
      font-weight: 600;
      flex: 1;
    }
  }

  .stats-grid {
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: 12px;
    margin-bottom: 12px;

    .stat-item {
      text-align: center;
      padding: 12px 8px;
      border: 1px solid var(--el-border-color-light);
      border-radius: 8px;

      .stat-value {
        font-size: 22px;
        font-weight: 600;
        margin-bottom: 4px;

        &.success { color: var(--el-color-success); }
        &.danger { color: var(--el-color-danger); }
        &.info { color: var(--el-color-primary); }
      }

      .stat-label {
        font-size: 13px;
        color: var(--el-text-color-secondary);
      }
    }
  }

  .last-update {
    font-size: 13px;
    color: var(--el-text-color-secondary);
  }

  .warm-section {
    .warm-result {
      margin-top: 12px;
    }

    .batch-actions {
      display: flex;
      gap: 12px;
      flex-wrap: wrap;
      margin-bottom: 16px;
    }

    .batch-progress {
      margin-top: 16px;
      padding: 16px;
      background: var(--el-fill-color-light);
      border-radius: 8px;

      .progress-header {
        display: flex;
        align-items: center;
        gap: 12px;
        margin-bottom: 12px;

        .progress-text {
          font-size: 14px;
          color: var(--el-text-color-regular);

          .failed-count {
            color: var(--el-color-danger);
          }
        }
      }

      .batch-results {
        margin-top: 12px;
        max-height: 200px;
        overflow-y: auto;

        .batch-result-item {
          display: flex;
          align-items: center;
          gap: 8px;
          padding: 4px 0;
          font-size: 13px;

          .batch-result-msg {
            color: var(--el-text-color-secondary);
          }
        }
      }
    }
  }

  .list-card {
    .empty-state {
      padding: 20px 0;
    }

    .load-more {
      text-align: center;
      padding-top: 8px;
    }
  }
}

@media (max-width: 768px) {
  .market-cache-manager {
    .stats-grid {
      grid-template-columns: repeat(2, 1fr);
    }
  }
}
</style>
