<template>
  <div class="market-cache-status">
    <el-card class="status-card" shadow="hover">
      <template #header>
        <div class="card-header">
          <el-icon class="header-icon"><Connection /></el-icon>
          <span class="header-title">{{ marketLabel }}数据源状态</span>
          <el-button
            type="primary"
            size="small"
            :loading="refreshing"
            @click="refreshStatus"
          >
            <el-icon><Refresh /></el-icon>
            刷新
          </el-button>
        </div>
      </template>

      <div v-loading="loading" class="status-content">
        <div v-if="error" class="error-message">
          <el-alert
            :title="error"
            type="error"
            :closable="false"
            show-icon
          />
        </div>

        <div v-else-if="sources.length > 0" class="sources-list">
          <div
            v-for="source in sources"
            :key="source.name"
            class="source-item"
            :class="{ 'available': source.available, 'unavailable': !source.available }"
          >
            <div class="source-header">
              <div class="source-info">
                <el-tag
                  :type="source.available ? 'success' : 'danger'"
                  size="small"
                  class="status-tag"
                >
                  {{ source.available ? '可用' : '不可用' }}
                </el-tag>
                <span class="source-name">{{ formatSourceName(source.name) }}</span>
                <el-tag v-if="source.priority > 0" size="small" type="info" class="priority-tag">
                  优先级: {{ source.priority }}
                </el-tag>
                <el-tag v-else size="small" type="info" class="priority-tag">
                  未配置优先级
                </el-tag>
              </div>
              <div class="source-actions">
                <el-button
                  size="small"
                  type="primary"
                  link
                  :loading="testingSource === source.name"
                  @click="testSingleSource(source.name)"
                >
                  <el-icon><Operation /></el-icon>
                  测试
                </el-button>
              </div>
            </div>
            <div class="source-description">
              {{ source.description }}
            </div>

            <!-- 测试结果展示 -->
            <div v-if="testResults[source.name]" class="test-results">
              <el-divider content-position="left">
                <span class="divider-text">最后测试结果</span>
              </el-divider>
              <div class="test-result-message">
                <el-alert
                  :title="testResults[source.name].message"
                  :type="testResults[source.name].available ? 'success' : 'error'"
                  :closable="false"
                  show-icon
                />
              </div>
            </div>
          </div>
        </div>

        <div v-else class="empty-state">
          <el-empty description="暂无数据源信息" />
        </div>
      </div>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { Connection, Refresh, Operation } from '@element-plus/icons-vue'
import {
  getMarketSourcesStatus,
  testMarketSources,
  type MarketSourceStatusEnhanced,
  type DataSourceTestResult,
  type MarketType,
} from '@/api/sync'

interface Props {
  market: MarketType
}

const props = defineProps<Props>()

const marketLabel = computed(() => props.market === 'HK' ? '港股' : '美股')

const loading = ref(false)
const refreshing = ref(false)
const error = ref('')
const sources = ref<MarketSourceStatusEnhanced[]>([])
const testResults = ref<Record<string, DataSourceTestResult>>({})
const testingSource = ref('')

const formatSourceName = (name: string) => {
  const map: Record<string, string> = {
    akshare_hk: 'AKShare',
    yfinance_hk: 'YFinance',
    yfinance_us: 'YFinance',
    finnhub_us: 'Finnhub',
  }
  return map[name] || name.toUpperCase()
}

const fetchSources = async () => {
  try {
    loading.value = true
    error.value = ''
    const response = await getMarketSourcesStatus(props.market)
    if (response.success) {
      sources.value = response.data.sort((a, b) => b.priority - a.priority)
    } else {
      error.value = response.message || '获取数据源状态失败'
    }
  } catch (err: any) {
    error.value = err.message || '网络请求失败'
  } finally {
    loading.value = false
  }
}

const refreshStatus = async () => {
  refreshing.value = true
  await fetchSources()
  refreshing.value = false
  ElMessage.success('数据源状态已刷新')
}

const testSingleSource = async (sourceName: string) => {
  try {
    testingSource.value = sourceName
    ElMessage.info(`正在测试 ${formatSourceName(sourceName)}，请稍候...`)

    const response = await testMarketSources(props.market, sourceName)
    if (response.success) {
      const results = response.data.test_results
      const sourceResult = results.find(r => r.name === sourceName)
      if (sourceResult) {
        testResults.value[sourceName] = sourceResult
        if (sourceResult.available) {
          ElMessage.success(`${formatSourceName(sourceName)} 连接成功`)
        } else {
          ElMessage.warning(`${formatSourceName(sourceName)} 连接失败: ${sourceResult.message}`)
        }
      }
    } else {
      ElMessage.error(`测试失败: ${response.message}`)
    }
  } catch (err: any) {
    if (err.code === 'ECONNABORTED') {
      ElMessage.error(`测试超时: ${formatSourceName(sourceName)} 测试时间过长，请稍后重试`)
    } else {
      ElMessage.error(`测试失败: ${err.message}`)
    }
  } finally {
    testingSource.value = ''
  }
}

onMounted(() => {
  fetchSources()
})

watch(() => props.market, () => {
  testResults.value = {}
  fetchSources()
})
</script>

<style scoped lang="scss">
.market-cache-status {
  .status-card {
    .card-header {
      display: flex;
      align-items: center;
      justify-content: space-between;

      .header-icon {
        margin-right: 8px;
        color: var(--el-color-primary);
      }

      .header-title {
        font-weight: 600;
        flex: 1;
      }
    }
  }

  .status-content {
    min-height: 120px;
  }

  .sources-list {
    .source-item {
      padding: 16px;
      border: 1px solid var(--el-border-color-light);
      border-radius: 8px;
      margin-bottom: 12px;
      transition: all 0.3s ease;

      &.available {
        border-color: var(--el-color-success-light-7);
        background-color: var(--el-color-success-light-9);
      }

      &.unavailable {
        border-color: var(--el-color-danger-light-7);
        background-color: var(--el-color-danger-light-9);
      }

      &:hover {
        box-shadow: 0 2px 8px rgba(0, 0, 0, 0.1);
      }

      .source-header {
        display: flex;
        align-items: center;
        justify-content: space-between;
        margin-bottom: 8px;

        .source-info {
          display: flex;
          align-items: center;
          gap: 8px;

          .source-name {
            font-weight: 600;
            font-size: 16px;
          }
        }
      }

      .source-description {
        color: var(--el-text-color-regular);
        font-size: 14px;
        line-height: 1.5;
      }

      .test-results {
        margin-top: 16px;

        .divider-text {
          font-size: 12px;
          color: var(--el-text-color-secondary);
        }
      }
    }
  }

  .error-message {
    margin-bottom: 16px;
  }

  .empty-state {
    text-align: center;
    padding: 40px 0;
  }
}
</style>
