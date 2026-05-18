<template>
  <div class="market-cache-history">
    <el-card shadow="hover">
      <template #header>
        <div class="card-header">
          <el-icon class="header-icon"><Clock /></el-icon>
          <span class="header-title">最近缓存活动</span>
          <el-button
            size="small"
            :loading="loading"
            @click="fetchHistory(1)"
          >
            刷新
          </el-button>
        </div>
      </template>

      <div v-loading="loading">
        <div v-if="records.length" class="history-timeline">
          <el-timeline>
            <el-timeline-item
              v-for="item in records"
              :key="item.symbol + item.updated_at"
              :timestamp="formatTime(item.updated_at)"
              placement="top"
              :type="getSourceType(item.data_source)"
            >
              <div class="timeline-content">
                <div class="timeline-header">
                  <span class="stock-symbol">{{ item.symbol }}</span>
                  <span v-if="item.name" class="stock-name">{{ item.name }}</span>
                </div>
                <div class="timeline-meta">
                  <el-tag size="small" type="info">{{ item.data_source }}</el-tag>
                </div>
              </div>
            </el-timeline-item>
          </el-timeline>

          <div v-if="hasMore" class="load-more">
            <el-button size="small" text :loading="loadingMore" @click="loadMore">
              加载更多
            </el-button>
          </div>
        </div>

        <el-empty v-else description="暂无缓存记录" :image-size="60" />
      </div>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, watch } from 'vue'
import { Clock } from '@element-plus/icons-vue'
import {
  getMarketCacheList,
  type MarketType,
} from '@/api/sync'

interface Props {
  market: MarketType
}

const props = defineProps<Props>()

const loading = ref(false)
const loadingMore = ref(false)
const records = ref<Array<{ symbol: string; name?: string; data_source: string; updated_at: string }>>([])
const currentPage = ref(1)
const hasMore = ref(false)

const formatTime = (isoString: string) => {
  if (!isoString) return ''
  try {
    const date = new Date(isoString)
    return date.toLocaleString('zh-CN', {
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
    })
  } catch {
    return isoString
  }
}

const getSourceType = (source: string): 'success' | 'primary' | 'warning' | 'info' => {
  if (source.includes('akshare')) return 'success'
  if (source.includes('yfinance')) return 'primary'
  if (source.includes('finnhub')) return 'warning'
  return 'info'
}

const fetchHistory = async (page = 1) => {
  try {
    if (page === 1) {
      loading.value = true
    } else {
      loadingMore.value = true
    }

    const res = await getMarketCacheList(props.market, page, 15)
    if (res.success) {
      if (page === 1) {
        records.value = res.data.records || []
      } else {
        records.value.push(...(res.data.records || []))
      }
      currentPage.value = page
      hasMore.value = res.data.has_more
    }
  } catch (e: any) {
    console.error('获取缓存历史失败:', e)
  } finally {
    loading.value = false
    loadingMore.value = false
  }
}

const loadMore = () => {
  fetchHistory(currentPage.value + 1)
}

onMounted(() => fetchHistory(1))

watch(() => props.market, () => {
  records.value = []
  fetchHistory(1)
})
</script>

<style scoped lang="scss">
.market-cache-history {
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

  .history-timeline {
    .timeline-content {
      .timeline-header {
        display: flex;
        align-items: center;
        gap: 8px;
        margin-bottom: 4px;

        .stock-symbol {
          font-weight: 600;
          font-size: 15px;
        }

        .stock-name {
          color: var(--el-text-color-secondary);
          font-size: 14px;
        }
      }

      .timeline-meta {
        display: flex;
        gap: 8px;
      }
    }
  }

  .load-more {
    text-align: center;
    padding-top: 8px;
  }
}
</style>
