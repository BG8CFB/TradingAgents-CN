<template>
  <div class="multi-source-sync">
    <!-- 页面头部 -->
    <div class="page-header">
      <div class="header-content">
        <div class="header-info">
          <h1 class="page-title">
            <el-icon class="title-icon"><Connection /></el-icon>
            多数据源同步
          </h1>
          <p class="page-description">
            管理和监控多个数据源的股票基础信息同步，支持自动fallback和优先级配置
          </p>
        </div>
        <div class="header-actions">
          <el-button
            type="primary"
            size="large"
            :loading="testing"
            @click="runFullTest"
          >
            <el-icon><Operation /></el-icon>
            全面测试
          </el-button>
        </div>
      </div>
    </div>

    <!-- 市场切换 Tab -->
    <el-tabs v-model="activeTab" class="market-tabs">
      <!-- A股 Tab -->
      <el-tab-pane label="A股" name="cn">
        <div class="page-content">
          <el-row :gutter="24">
            <!-- 左侧列 -->
            <el-col :lg="12" :md="24" :sm="24">
              <!-- 数据源状态 -->
              <div class="content-section">
                <DataSourceStatus ref="dataSourceStatusRef" />
              </div>

              <!-- 使用建议 -->
              <div class="content-section">
                <SyncRecommendations />
              </div>
            </el-col>

            <!-- 右侧列 -->
            <el-col :lg="12" :md="24" :sm="24">
              <!-- 同步控制 -->
              <div class="content-section">
                <SyncControl @sync-completed="handleSyncCompleted" />
              </div>

              <!-- 同步历史 -->
              <div class="content-section">
                <SyncHistory />
              </div>
            </el-col>
          </el-row>
        </div>
      </el-tab-pane>

      <!-- 港股 Tab -->
      <el-tab-pane label="港股" name="hk">
        <div class="page-content">
          <el-row :gutter="24">
            <el-col :lg="12" :md="24" :sm="24">
              <el-card shadow="never">
                <template #header>
                  <span>港股数据源状态</span>
                </template>
                <div v-if="hkLoading" class="loading-placeholder">
                  <el-skeleton :rows="2" animated />
                </div>
                <div v-else-if="hkSources.length">
                  <div
                    v-for="src in hkSources"
                    :key="src.name"
                    class="source-item"
                  >
                    <el-tag :type="src.available ? 'success' : 'danger'" size="small">
                      {{ src.name }}
                    </el-tag>
                    <span class="source-status">
                      {{ src.available ? '可用' : '不可用' }}
                    </span>
                  </div>
                </div>
                <el-empty v-else description="暂无数据源信息" :image-size="60" />
              </el-card>
            </el-col>

            <el-col :lg="12" :md="24" :sm="24">
              <el-card shadow="never">
                <template #header>
                  <span>缓存管理</span>
                </template>
                <div v-if="hkCacheStats" class="cache-info">
                  <p>市场：{{ hkCacheStats.market }}</p>
                  <p v-if="hkCacheStats.cache_hours">缓存时长：{{ hkCacheStats.cache_hours }} 小时</p>
                  <p v-if="hkCacheStats.available_sources?.length">
                    可用数据源：{{ hkCacheStats.available_sources.join(', ') }}
                  </p>
                </div>

                <div class="cache-actions">
                  <el-input
                    v-model="hkWarmSymbol"
                    placeholder="输入港股代码，如 00700"
                    style="margin-bottom: 12px"
                    clearable
                  >
                    <template #append>
                      <el-button
                        :loading="hkWarming"
                        @click="handleWarmHK"
                      >
                        刷新缓存
                      </el-button>
                    </template>
                  </el-input>
                  <el-button
                    type="danger"
                    plain
                    size="small"
                    @click="handleClearHKCache"
                  >
                    清理缓存
                  </el-button>
                </div>
              </el-card>
            </el-col>
          </el-row>
        </div>
      </el-tab-pane>

      <!-- 美股 Tab -->
      <el-tab-pane label="美股" name="us">
        <div class="page-content">
          <el-row :gutter="24">
            <el-col :lg="12" :md="24" :sm="24">
              <el-card shadow="never">
                <template #header>
                  <span>美股数据源状态</span>
                </template>
                <div v-if="usLoading" class="loading-placeholder">
                  <el-skeleton :rows="2" animated />
                </div>
                <div v-else-if="usSources.length">
                  <div
                    v-for="src in usSources"
                    :key="src.name"
                    class="source-item"
                  >
                    <el-tag :type="src.available ? 'success' : 'danger'" size="small">
                      {{ src.name }}
                    </el-tag>
                    <span class="source-status">
                      {{ src.available ? '可用' : '不可用' }}
                    </span>
                  </div>
                </div>
                <el-empty v-else description="暂无数据源信息" :image-size="60" />
              </el-card>
            </el-col>

            <el-col :lg="12" :md="24" :sm="24">
              <el-card shadow="never">
                <template #header>
                  <span>缓存管理</span>
                </template>
                <div v-if="usCacheStats" class="cache-info">
                  <p>市场：{{ usCacheStats.market }}</p>
                  <p v-if="usCacheStats.cache_hours">缓存时长：{{ usCacheStats.cache_hours }} 小时</p>
                  <p v-if="usCacheStats.available_sources?.length">
                    可用数据源：{{ usCacheStats.available_sources.join(', ') }}
                  </p>
                </div>

                <div class="cache-actions">
                  <el-input
                    v-model="usWarmSymbol"
                    placeholder="输入美股代码，如 AAPL"
                    style="margin-bottom: 12px"
                    clearable
                  >
                    <template #append>
                      <el-button
                        :loading="usWarming"
                        @click="handleWarmUS"
                      >
                        刷新缓存
                      </el-button>
                    </template>
                  </el-input>
                  <el-button
                    type="danger"
                    plain
                    size="small"
                    @click="handleClearUSCache"
                  >
                    清理缓存
                  </el-button>
                </div>
              </el-card>
            </el-col>
          </el-row>
        </div>
      </el-tab-pane>
    </el-tabs>

    <!-- 测试结果对话框 -->
    <el-dialog
      v-model="testDialogVisible"
      title="全面测试结果"
      width="80%"
      :close-on-click-modal="false"
    >
      <div v-if="testResults" class="test-results-dialog">
        <div class="test-summary">
          <el-alert
            :title="`测试完成，共测试 ${testResults.length} 个数据源`"
            :type="getOverallTestResult()"
            :closable="false"
            show-icon
          />
        </div>

        <div class="test-details">
          <el-row :gutter="16">
            <el-col
              v-for="result in testResults"
              :key="result.name"
              :lg="8"
              :md="12"
              :sm="24"
            >
              <div class="test-result-item">
                <div class="result-header">
                  <el-tag
                    :type="result.available ? 'success' : 'danger'"
                    size="large"
                  >
                    {{ result.name.toUpperCase() }}
                  </el-tag>
                  <span class="priority-info">优先级: {{ result.priority }}</span>
                </div>

                <div class="result-message">
                  <el-alert
                    :title="result.message"
                    :type="result.available ? 'success' : 'error'"
                    :closable="false"
                    show-icon
                  />
                </div>
              </div>
            </el-col>
          </el-row>
        </div>
      </div>

      <template #footer>
        <el-button @click="testDialogVisible = false">关闭</el-button>
        <el-button type="primary" @click="exportTestResults">
          <el-icon><Download /></el-icon>
          导出结果
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import {
  Connection,
  Operation,
  Download
} from '@element-plus/icons-vue'
import {
  testDataSources,
  getHKSourcesStatus,
  getHKCacheStats,
  warmHKCache,
  clearHKCache,
  getUSSourcesStatus,
  getUSCacheStats,
  warmUSCache,
  clearUSCache,
  type DataSourceTestResult,
  type MarketSourceStatus,
  type MarketCacheStats,
} from '@/api/sync'
import DataSourceStatus from '@/components/Sync/DataSourceStatus.vue'
import SyncControl from '@/components/Sync/SyncControl.vue'
import SyncRecommendations from '@/components/Sync/SyncRecommendations.vue'
import SyncHistory from '@/components/Sync/SyncHistory.vue'

// A股
const testing = ref(false)
const testDialogVisible = ref(false)
const testResults = ref<DataSourceTestResult[] | null>(null)
const dataSourceStatusRef = ref()
const activeTab = ref('cn')

// 港股
const hkLoading = ref(false)
const hkSources = ref<MarketSourceStatus[]>([])
const hkCacheStats = ref<MarketCacheStats | null>(null)
const hkWarmSymbol = ref('')
const hkWarming = ref(false)

// 美股
const usLoading = ref(false)
const usSources = ref<MarketSourceStatus[]>([])
const usCacheStats = ref<MarketCacheStats | null>(null)
const usWarmSymbol = ref('')
const usWarming = ref(false)

// Tab 切换时加载数据
watch(activeTab, (tab) => {
  if (tab === 'hk') loadHKData()
  if (tab === 'us') loadUSData()
})

const loadHKData = async () => {
  hkLoading.value = true
  try {
    const [srcRes, statsRes] = await Promise.all([
      getHKSourcesStatus(),
      getHKCacheStats(),
    ])
    hkSources.value = srcRes.data || []
    hkCacheStats.value = statsRes.data || null
  } catch (e: any) {
    console.error('加载港股数据失败:', e)
  } finally {
    hkLoading.value = false
  }
}

const loadUSData = async () => {
  usLoading.value = true
  try {
    const [srcRes, statsRes] = await Promise.all([
      getUSSourcesStatus(),
      getUSCacheStats(),
    ])
    usSources.value = srcRes.data || []
    usCacheStats.value = statsRes.data || null
  } catch (e: any) {
    console.error('加载美股数据失败:', e)
  } finally {
    usLoading.value = false
  }
}

const handleWarmHK = async () => {
  if (!hkWarmSymbol.value.trim()) {
    ElMessage.warning('请输入港股代码')
    return
  }
  hkWarming.value = true
  try {
    const res = await warmHKCache(hkWarmSymbol.value.trim())
    if (res.success) {
      ElMessage.success(res.message || '缓存刷新成功')
      await loadHKData()
    } else {
      ElMessage.error(res.message || '缓存刷新失败')
    }
  } catch (e: any) {
    ElMessage.error(`缓存刷新失败: ${e.message}`)
  } finally {
    hkWarming.value = false
  }
}

const handleWarmUS = async () => {
  if (!usWarmSymbol.value.trim()) {
    ElMessage.warning('请输入美股代码')
    return
  }
  usWarming.value = true
  try {
    const res = await warmUSCache(usWarmSymbol.value.trim())
    if (res.success) {
      ElMessage.success(res.message || '缓存刷新成功')
      await loadUSData()
    } else {
      ElMessage.error(res.message || '缓存刷新失败')
    }
  } catch (e: any) {
    ElMessage.error(`缓存刷新失败: ${e.message}`)
  } finally {
    usWarming.value = false
  }
}

const handleClearHKCache = async () => {
  try {
    const res = await clearHKCache()
    ElMessage.success(res.message || '缓存清理完成')
    await loadHKData()
  } catch (e: any) {
    ElMessage.error(`清理失败: ${e.message}`)
  }
}

const handleClearUSCache = async () => {
  try {
    const res = await clearUSCache()
    ElMessage.success(res.message || '缓存清理完成')
    await loadUSData()
  } catch (e: any) {
    ElMessage.error(`清理失败: ${e.message}`)
  }
}

// A股测试
const runFullTest = async () => {
  try {
    testing.value = true
    ElMessage.info('正在进行全面测试，请稍候...')
    const response = await testDataSources()
    if (response.success) {
      testResults.value = response.data.test_results
      testDialogVisible.value = true
      const availableCount = testResults.value.filter(r => r.available).length
      ElMessage.success(`全面测试完成: ${availableCount}/${testResults.value.length} 数据源可用`)
    } else {
      ElMessage.error(`测试失败: ${response.message}`)
    }
  } catch (err: any) {
    console.error('全面测试失败:', err)
    if (err.code === 'ECONNABORTED') {
      ElMessage.error('测试超时，请稍后重试。请确保网络连接稳定。')
    } else {
      ElMessage.error(`测试失败: ${err.message}`)
    }
  } finally {
    testing.value = false
  }
}

const getOverallTestResult = (): 'success' | 'warning' | 'info' | 'error' => {
  if (!testResults.value) return 'info'
  const hasFailure = testResults.value.some(result => !result.available)
  return hasFailure ? 'warning' : 'success'
}

const exportTestResults = () => {
  if (!testResults.value) return

  const data = {
    timestamp: new Date().toISOString(),
    results: testResults.value
  }

  const blob = new Blob([JSON.stringify(data, null, 2)], {
    type: 'application/json'
  })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `data-source-test-results-${new Date().toISOString().split('T')[0]}.json`
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  URL.revokeObjectURL(url)

  ElMessage.success('测试结果已导出')
}

const handleSyncCompleted = (status: string) => {
  console.log('同步完成事件，状态:', status)
}
</script>

<style scoped lang="scss">
.multi-source-sync {
  .page-header {
    margin-bottom: 24px;
    padding: 24px;
    background: linear-gradient(135deg, var(--el-color-primary-light-9) 0%, var(--el-color-primary-light-8) 100%);
    border-radius: 12px;

    .header-content {
      display: flex;
      align-items: center;
      justify-content: space-between;

      .header-info {
        .page-title {
          display: flex;
          align-items: center;
          margin: 0 0 8px 0;
          font-size: 28px;
          font-weight: 600;
          color: var(--el-text-color-primary);

          .title-icon {
            margin-right: 12px;
            color: var(--el-color-primary);
          }
        }

        .page-description {
          margin: 0;
          font-size: 16px;
          color: var(--el-text-color-regular);
          line-height: 1.5;
        }
      }

      .header-actions {
        flex-shrink: 0;
      }
    }
  }

  .market-tabs {
    margin-bottom: 16px;
  }

  .page-content {
    .content-section {
      margin-bottom: 24px;

      &:last-child {
        margin-bottom: 0;
      }
    }
  }

  .source-item {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 8px 0;
    border-bottom: 1px solid var(--el-border-color-lighter);

    &:last-child {
      border-bottom: none;
    }

    .source-status {
      font-size: 13px;
      color: var(--el-text-color-secondary);
    }
  }

  .cache-info {
    margin-bottom: 16px;

    p {
      margin: 4px 0;
      font-size: 14px;
      color: var(--el-text-color-regular);
    }
  }

  .cache-actions {
    margin-top: 12px;
  }

  .test-results-dialog {
    .test-summary {
      margin-bottom: 24px;
    }

    .test-details {
      .test-result-item {
        margin-bottom: 24px;
        padding: 20px;
        border: 1px solid var(--el-border-color-light);
        border-radius: 8px;

        &:last-child {
          margin-bottom: 0;
        }

        .result-header {
          display: flex;
          align-items: center;
          gap: 12px;
          margin-bottom: 16px;

          .priority-info {
            font-size: 14px;
            color: var(--el-text-color-secondary);
          }
        }

        .result-tests {
          .test-item {
            padding: 12px;
            border: 1px solid var(--el-border-color-lighter);
            border-radius: 6px;
            height: 100%;
          }
        }
      }
    }
  }
}

@media (max-width: 768px) {
  .multi-source-sync {
    .page-header {
      .header-content {
        flex-direction: column;
        align-items: flex-start;
        gap: 16px;

        .header-actions {
          width: 100%;

          .el-button {
            width: 100%;
          }
        }
      }
    }
  }
}
</style>
