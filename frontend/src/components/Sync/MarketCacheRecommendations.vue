<template>
  <div class="market-cache-recommendations">
    <el-card shadow="hover">
      <template #header>
        <div class="card-header">
          <el-icon class="header-icon"><Opportunity /></el-icon>
          <span class="header-title">使用建议</span>
        </div>
      </template>

      <div v-loading="loading">
        <template v-if="data">
          <!-- 推荐主数据源 -->
          <div v-if="data.primary_source" class="primary-source">
            <div class="source-badge">
              <el-tag type="success" size="large" effect="dark">推荐主数据源</el-tag>
            </div>
            <div class="source-info">
              <h4 class="source-name">{{ data.primary_source.name }}</h4>
              <el-tag size="small" type="info">优先级: {{ data.primary_source.priority }}</el-tag>
              <p class="source-reason">{{ data.primary_source.reason }}</p>
            </div>
          </div>

          <!-- 备用数据源 -->
          <div v-if="data.fallback_sources?.length" class="fallback-sources">
            <h4 class="section-title">备用数据源</h4>
            <div class="fallback-list">
              <div v-for="src in data.fallback_sources" :key="src.name" class="fallback-item">
                <el-tag size="small">{{ src.name }}</el-tag>
                <span class="fallback-priority">优先级: {{ src.priority }}</span>
              </div>
            </div>
          </div>

          <!-- 使用建议 -->
          <div v-if="data.suggestions?.length" class="suggestions">
            <h4 class="section-title">使用建议</h4>
            <ul class="suggestion-list">
              <li v-for="(tip, idx) in data.suggestions" :key="idx">{{ tip }}</li>
            </ul>
          </div>

          <!-- 警告 -->
          <div v-if="data.warnings?.length" class="warnings">
            <el-alert
              v-for="(warning, idx) in data.warnings"
              :key="idx"
              :title="warning"
              type="warning"
              :closable="false"
              show-icon
              style="margin-bottom: 8px"
            />
          </div>

          <!-- 环境变量配置 -->
          <div v-if="data.env_config" class="env-config">
            <el-collapse>
              <el-collapse-item title="环境变量配置" name="env">
                <p class="env-description">{{ data.env_config.description }}</p>
                <div v-if="data.env_config.example" class="env-example">
                  <code>{{ data.env_config.example }}</code>
                </div>
              </el-collapse-item>
            </el-collapse>
          </div>
        </template>

        <el-empty v-else-if="!loading" description="暂无建议信息" :image-size="60" />
      </div>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, watch } from 'vue'
import { Opportunity } from '@element-plus/icons-vue'
import {
  getMarketRecommendations,
  type MarketRecommendations,
  type MarketType,
} from '@/api/sync'

interface Props {
  market: MarketType
}

const props = defineProps<Props>()

const loading = ref(false)
const data = ref<MarketRecommendations | null>(null)

const fetchData = async () => {
  try {
    loading.value = true
    const res = await getMarketRecommendations(props.market)
    if (res.success) {
      data.value = res.data
    }
  } catch (e: any) {
    console.error('获取建议失败:', e)
  } finally {
    loading.value = false
  }
}

onMounted(fetchData)

watch(() => props.market, fetchData)
</script>

<style scoped lang="scss">
.market-cache-recommendations {
  .card-header {
    display: flex;
    align-items: center;

    .header-icon {
      margin-right: 8px;
      color: var(--el-color-primary);
    }

    .header-title {
      font-weight: 600;
    }
  }

  .primary-source {
    display: flex;
    gap: 16px;
    padding: 16px;
    background: var(--el-color-success-light-9);
    border: 1px solid var(--el-color-success-light-7);
    border-radius: 8px;
    margin-bottom: 20px;

    .source-badge {
      flex-shrink: 0;
    }

    .source-info {
      .source-name {
        margin: 0 0 8px;
        font-size: 18px;
        font-weight: 600;
      }

      .source-reason {
        margin: 8px 0 0;
        font-size: 14px;
        color: var(--el-text-color-regular);
      }
    }
  }

  .section-title {
    margin: 0 0 12px;
    font-size: 15px;
    font-weight: 600;
    color: var(--el-text-color-primary);
  }

  .fallback-sources {
    margin-bottom: 20px;

    .fallback-list {
      display: flex;
      flex-wrap: wrap;
      gap: 12px;

      .fallback-item {
        display: flex;
        align-items: center;
        gap: 8px;

        .fallback-priority {
          font-size: 13px;
          color: var(--el-text-color-secondary);
        }
      }
    }
  }

  .suggestions {
    margin-bottom: 20px;

    .suggestion-list {
      margin: 0;
      padding-left: 20px;

      li {
        margin-bottom: 6px;
        font-size: 14px;
        color: var(--el-text-color-regular);
        line-height: 1.6;
      }
    }
  }

  .warnings {
    margin-bottom: 16px;
  }

  .env-config {
    .env-description {
      font-size: 14px;
      color: var(--el-text-color-regular);
      margin: 0 0 8px;
    }

    .env-example {
      padding: 8px 12px;
      background: var(--el-fill-color);
      border-radius: 4px;

      code {
        font-family: monospace;
        font-size: 13px;
        color: var(--el-color-primary);
      }
    }
  }
}
</style>
