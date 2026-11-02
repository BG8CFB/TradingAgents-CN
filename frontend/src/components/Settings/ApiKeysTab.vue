<template>
  <div>
    <el-card class="config-content" shadow="never">
      <template #header>
        <div class="card-header">
          <h3>API密钥状态</h3>
          <el-button @click="loadProviders" :loading="providersLoading">
            <el-icon><Refresh /></el-icon>
            刷新状态
          </el-button>
        </div>
      </template>

      <div class="api-keys-content" v-loading="providersLoading">
        <el-row :gutter="24">
          <el-col :span="12">
            <h4>🔑 AI厂家密钥状态</h4>
            <div
              v-for="provider in providers"
              :key="provider.id"
              class="api-key-item"
            >
              <el-icon><Key /></el-icon>
              <span class="key-name">{{ provider.display_name }}</span>
              <el-tag
                :type="getKeyStatusType(provider)"
                size="small"
              >
                {{ getKeyStatusText(provider) }}
              </el-tag>
              <el-button
                v-if="!provider.extra_config?.has_api_key"
                size="small"
                type="primary"
                link
                @click="editProvider(provider)"
              >
                配置
              </el-button>
            </div>

            <div v-if="providers.length === 0" class="empty-state">
              <el-empty description="暂无厂家配置">
                <el-button type="primary" @click="goToProvidersTab">
                  添加厂家
                </el-button>
              </el-empty>
            </div>
          </el-col>

          <el-col :span="12">
            <h4>📊 配置统计</h4>
            <div class="stats-grid">
              <div class="stat-item">
                <div class="stat-number">{{ providers.length }}</div>
                <div class="stat-label">总厂家数</div>
              </div>
              <div class="stat-item">
                <div class="stat-number">{{ configuredProvidersCount }}</div>
                <div class="stat-label">已配置密钥</div>
              </div>
              <div class="stat-item">
                <div class="stat-number">{{ activeProvidersCount }}</div>
                <div class="stat-label">启用厂家</div>
              </div>
              <div class="stat-item">
                <div class="stat-number">{{ llmConfigs.length }}</div>
                <div class="stat-label">配置模型</div>
              </div>
            </div>
          </el-col>
        </el-row>

        <el-divider />

        <div class="api-key-help">
          <h4>💡 配置说明</h4>
          <el-row :gutter="16">
            <el-col :span="8">
              <el-card shadow="never" class="help-card">
                <h5>如何配置API密钥？</h5>
                <ol>
                  <li>在"厂家管理"中添加AI厂家</li>
                  <li>编辑厂家信息，填入API密钥</li>
                  <li>在"大模型配置"中选择厂家和模型</li>
                  <li>系统自动使用厂家的API密钥</li>
                </ol>
              </el-card>
            </el-col>
            <el-col :span="8">
              <el-card shadow="never" class="help-card">
                <h5>🔄 从环境变量迁移</h5>
                <p>如果你之前在 .env 文件中配置了API密钥，可以一键迁移到厂家管理：</p>
                <el-button
                  type="primary"
                  @click="migrateFromEnv"
                  :loading="migrateLoading"
                  size="small"
                >
                  迁移环境变量
                </el-button>
              </el-card>
            </el-col>
            <el-col :span="8">
              <el-alert
                title="🔒 安全提示"
                type="warning"
                description="敏感密钥通过环境变量/运维配置注入，后端响应已统一脱敏；请勿在界面或导出文件中保存真实密钥。"
                show-icon
                :closable="false"
              />
            </el-col>
          </el-row>
        </div>
      </div>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Refresh, Key } from '@element-plus/icons-vue'
import { configApi, type LLMProvider, type LLMConfig } from '@/api/config'

// 厂家编辑对话框由父组件持有（与「厂家管理」tab 共用），此处仅抛出事件；
// navigate 用于空状态跳转到其它 tab（原实现直接切换 activeTab，不触发数据加载）
const emit = defineEmits<{
  'edit-provider': [provider: LLMProvider]
  'navigate': [tab: string]
}>()

// 响应式数据
const providers = ref<LLMProvider[]>([])
const llmConfigs = ref<LLMConfig[]>([])
const providersLoading = ref(false)
const migrateLoading = ref(false)

// 加载厂家列表
const loadProviders = async () => {
  providersLoading.value = true
  try {
    const providerListResp = await configApi.getLLMProviders()
    providers.value = Array.isArray(providerListResp) ? providerListResp : providerListResp.data
  } catch (error) {
    console.error('❌ 加载厂家列表失败:', error)
    ElMessage.error('加载厂家列表失败')
  } finally {
    providersLoading.value = false
  }
}

// 加载大模型配置（本 tab 仅用于「配置模型」计数，不构建分组）
const loadLLMConfigs = async () => {
  try {
    const configsResp = await configApi.getLLMConfigs()
    llmConfigs.value = Array.isArray(configsResp) ? configsResp : configsResp.data
  } catch (error) {
    console.error('❌ 加载大模型配置失败:', error)
    ElMessage.error('加载大模型配置失败')
  }
}

// API密钥状态相关计算属性
const configuredProvidersCount = computed(() => {
  return providers.value.filter(p => p.extra_config?.has_api_key === true).length
})

const activeProvidersCount = computed(() => {
  return providers.value.filter(p => p.is_active).length
})

// 获取密钥状态类型
const getKeyStatusType = (provider: LLMProvider) => {
  if (!provider.extra_config?.has_api_key) {
    return 'info'
  }
  return provider.is_active ? 'success' : 'warning'
}

// 获取密钥状态文本
const getKeyStatusText = (provider: LLMProvider) => {
  if (!provider.extra_config?.has_api_key) {
    return '未配置'
  }
  if (!provider.is_active) {
    return '已配置(禁用)'
  }

  if (provider.extra_config?.source === 'environment') {
    return '已配置(环境变量)'
  }

  return '已配置'
}

// 编辑厂家（打开父组件持有的厂家对话框）
const editProvider = (provider: LLMProvider) => {
  emit('edit-provider', provider)
}

// 空状态跳转：原实现直接切到厂家管理 tab
const goToProvidersTab = () => {
  emit('navigate', 'providers')
}

// 从环境变量迁移
const migrateFromEnv = async () => {
  try {
    await ElMessageBox.confirm(
      '此操作将从 .env 文件中读取API密钥并创建对应的厂家配置。已存在的厂家配置不会被覆盖。',
      '确认迁移',
      { type: 'info' }
    )

    migrateLoading.value = true
    const result = await configApi.migrateEnvToProviders()

    ElMessage.success(result.message)

    // 重新加载厂家列表
    await loadProviders()

  } catch (error) {
    if (error !== 'cancel') {
      console.error('迁移失败:', error)
      ElMessage.error('迁移失败，请检查控制台错误信息')
    }
  } finally {
    migrateLoading.value = false
  }
}

// tab 激活时加载：厂家列表 + 模型配置（用于统计）
const load = async () => {
  await loadProviders()
  await loadLLMConfigs()
}

// 供父组件按 tab 懒加载，以及厂家对话框保存成功后刷新
defineExpose({ reload: load })
</script>

<style lang="scss" scoped>
.config-content {
  min-height: 500px;

  .card-header {
    display: flex;
    justify-content: space-between;
    align-items: center;

    h3 {
      margin: 0;
    }
  }

  .api-keys-content {
    h4 {
      margin: 0 0 16px 0;
      color: var(--el-text-color-primary);
    }

    .api-key-item {
      display: flex;
      align-items: center;
      gap: 12px;
      padding: 12px;
      margin-bottom: 8px;
      border-radius: 6px;
      background: var(--el-fill-color-lighter);
      border: 1px solid var(--el-border-color-light);

      .key-name {
        flex: 1;
        font-size: 14px;
        font-weight: 500;
        color: var(--el-text-color-primary);
      }
    }

    .empty-state {
      text-align: center;
      padding: 40px 20px;
    }

    .stats-grid {
      display: grid;
      grid-template-columns: repeat(2, 1fr);
      gap: 16px;
    }

    .stat-item {
      text-align: center;
      padding: 16px;
      background: var(--el-fill-color-lighter);
      border-radius: 8px;
      border: 1px solid var(--el-border-color-light);

      .stat-number {
        font-size: 24px;
        font-weight: bold;
        color: var(--el-color-primary);
        margin-bottom: 4px;
      }

      .stat-label {
        font-size: 12px;
        color: var(--el-text-color-regular);
      }
    }

    .api-key-help {
      margin-top: 24px;

      h4 {
        margin-bottom: 12px;
      }

      h5 {
        margin: 0 0 8px 0;
        color: var(--el-text-color-primary);
      }

      ol {
        margin: 0;
        padding-left: 20px;

        li {
          margin-bottom: 4px;
          color: var(--el-text-color-regular);
        }
      }

      .help-card {
        background: var(--el-fill-color-lighter);
      }
    }
  }
}
</style>
