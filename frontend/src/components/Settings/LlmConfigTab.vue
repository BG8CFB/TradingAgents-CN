<template>
  <div>
    <el-card class="config-content" shadow="never">
      <template #header>
        <div class="card-header">
          <h3>大模型配置</h3>
          <el-button type="primary" @click="showAddLLMDialog">
            <el-icon><Plus /></el-icon>
            添加模型
          </el-button>
        </div>
      </template>

      <div v-loading="llmLoading">
        <!-- 按厂家分组的卡片式布局 -->
        <div v-if="llmConfigGroups.length === 0" class="empty-state">
          <el-empty description="暂无大模型配置">
            <el-button type="primary" @click="showAddLLMDialog">
              <el-icon><Plus /></el-icon>
              添加第一个模型
            </el-button>
          </el-empty>
        </div>

        <div v-else class="provider-groups">
          <div
            v-for="group in llmConfigGroups"
            :key="group.provider"
            class="provider-group"
          >
            <!-- 厂家头部 -->
            <div class="provider-header">
              <div class="provider-info">
                <el-tag :type="getProviderTagType(group.provider)" size="large" class="provider-tag">
                  <el-icon><OfficeBuilding /></el-icon>
                  {{ group.display_name }}
                </el-tag>
                <span class="model-count">{{ group.models.length }} 个模型</span>
                <el-tag
                  :type="group.is_active ? 'success' : 'danger'"
                  size="small"
                  class="status-tag"
                >
                  {{ group.is_active ? '已启用' : '已禁用' }}
                </el-tag>
              </div>
              <div class="provider-actions">
                <el-button
                  size="small"
                  type="primary"
                  @click="addModelToProvider(group)"
                >
                  <el-icon><Plus /></el-icon>
                  添加模型
                </el-button>
                <el-button
                  size="small"
                  :type="group.is_active ? 'warning' : 'success'"
                  @click="toggleProviderStatus(group)"
                >
                  {{ group.is_active ? '禁用' : '启用' }}
                </el-button>
              </div>
            </div>

            <!-- 模型列表 - 表格式布局 -->
            <el-table :data="group.models" style="width: 100%" stripe>
              <!-- 模型名称 -->
              <el-table-column label="模型名称" width="200">
                <template #default="{ row }">
                  <div class="model-name-cell">
                    <div class="model-display-name">
                      {{ row.model_display_name || row.model_name }}
                      <el-tooltip
                        v-if="row.thinking_effort"
                        :content="`思考强度: ${thinkingEffortLabel(row.thinking_effort)}`"
                        placement="top"
                      >
                        <el-tag size="small" type="warning" class="thinking-badge">💭</el-tag>
                      </el-tooltip>
                    </div>
                    <div v-if="row.model_display_name" class="model-code-text">{{ row.model_name }}</div>
                  </div>
                </template>
              </el-table-column>

              <!-- 状态 -->
              <el-table-column label="状态" width="80" align="center">
                <template #default="{ row }">
                  <el-tag :type="row.enabled ? 'success' : 'danger'" size="small">
                    {{ row.enabled ? '启用' : '禁用' }}
                  </el-tag>
                </template>
              </el-table-column>

              <!-- 基础配置 -->
              <el-table-column label="基础配置" width="200">
                <template #default="{ row }">
                  <div class="config-cell">
                    <div>Token: {{ row.max_tokens }}</div>
                    <div>温度: {{ row.temperature }} | 超时: {{ row.timeout }}s</div>
                  </div>
                </template>
              </el-table-column>

              <!-- 定价 -->
              <el-table-column label="定价" width="180">
                <template #default="{ row }">
                  <div v-if="row.input_price_per_1k || row.output_price_per_1k" class="pricing-cell">
                    <div>输入: {{ formatPrice(row.input_price_per_1k) }} {{ row.currency || 'CNY' }}/1K</div>
                    <div>输出: {{ formatPrice(row.output_price_per_1k) }} {{ row.currency || 'CNY' }}/1K</div>
                  </div>
                  <span v-else class="text-muted">-</span>
                </template>
              </el-table-column>

              <!-- 操作 -->
              <el-table-column label="操作" width="260" fixed="right">
                <template #default="{ row }">
                  <el-button size="small" @click="editLLMConfig(row)">
                    编辑
                  </el-button>
                  <el-button
                    size="small"
                    type="primary"
                    @click="testLLMConfig(row)"
                  >
                    测试
                  </el-button>
                  <el-button
                    size="small"
                    :type="row.enabled ? 'warning' : 'success'"
                    @click="toggleLLMConfig(row)"
                  >
                    {{ row.enabled ? '禁用' : '启用' }}
                  </el-button>
                  <el-button
                    size="small"
                    type="danger"
                    @click="deleteLLMConfig(row)"
                  >
                    删除
                  </el-button>
                </template>
              </el-table-column>
            </el-table>
          </div>
        </div>
      </div>
    </el-card>

    <!-- 大模型配置对话框 -->
    <LLMConfigDialog
      v-model:visible="llmDialogVisible"
      :config="currentLLMConfig"
      @success="handleLLMConfigSuccess"
    />
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus, OfficeBuilding } from '@element-plus/icons-vue'
import { configApi, type LLMProvider, type LLMConfig } from '@/api/config'
import LLMConfigDialog from '@/views/Settings/components/LLMConfigDialog.vue'
import {
  DEFAULT_MAX_TOKENS,
  DEFAULT_TEMPERATURE,
  DEFAULT_TIMEOUT,
  DEFAULT_RETRY_TIMES,
  THINKING_EFFORT_OPTIONS,
} from '@/constants/llmDefaults'

// 思考档位值 → 中文标签（模型列表 💭 徽标 tooltip 用）
const thinkingEffortLabel = (value: string): string =>
  THINKING_EFFORT_OPTIONS.find(o => o.value === value)?.label || value

// 响应式数据
const llmConfigs = ref<LLMConfig[]>([])
const llmConfigGroups = ref<any[]>([])
const defaultLLM = ref<string>('')
const llmLoading = ref(false)

// 厂家列表与厂家信息映射（分组展示、显示名回退与状态切换依赖）
const providers = ref<LLMProvider[]>([])
const providerInfoMap = ref<Record<string, any>>({})

// 大模型配置对话框
const llmDialogVisible = ref(false)
const currentLLMConfig = ref<LLMConfig | null>(null)
const isEditingLLM = ref(false)

// 加载厂家信息到映射表（同时保留厂家列表供显示名查找与状态切换）
const loadProviderInfoMap = async () => {
  try {
    const providerListResp = await configApi.getLLMProviders()
    const list: LLMProvider[] = Array.isArray(providerListResp) ? providerListResp : providerListResp.data

    providers.value = list
    const map: Record<string, any> = {}

    list.forEach((provider: LLMProvider) => {
      map[provider.name] = {
        display_name: provider.display_name,
        description: provider.description,
        is_active: provider.is_active
      }
    })

    providerInfoMap.value = map
  } catch (error) {
    console.error('加载厂家信息映射失败:', error)
  }
}

const loadLLMConfigs = async () => {
  llmLoading.value = true
  try {
    const configsResp = await configApi.getLLMConfigs()
    llmConfigs.value = Array.isArray(configsResp) ? configsResp : configsResp.data

    // 获取默认LLM
    const systemConfig = await configApi.getSystemConfig()
    const sysData = systemConfig.data || systemConfig
    defaultLLM.value = sysData.default_llm || ''

    // 构建分组数据
    buildLLMConfigGroups()
  } catch (error) {
    console.error('❌ 加载大模型配置失败:', error)
    ElMessage.error('加载大模型配置失败')
  } finally {
    llmLoading.value = false
  }
}

// 构建大模型配置分组数据
const buildLLMConfigGroups = () => {
  // 按厂家分组
  const providerGroups: Record<string, LLMConfig[]> = {}

  llmConfigs.value.forEach(config => {
    const provider = config.provider
    if (!providerGroups[provider]) {
      providerGroups[provider] = []
    }
    providerGroups[provider].push(config)
  })

  // 构建分组数据
  const groups: any[] = []

  Object.entries(providerGroups).forEach(([provider, models]) => {
    // 获取厂家信息
    const providerInfo = providerInfoMap.value[provider] || {
      display_name: getProviderDisplayName(provider),
      description: `${getProviderDisplayName(provider)} 大模型服务`,
      is_active: true
    }

    // 创建厂家分组
    const group = {
      provider: provider,
      display_name: providerInfo.display_name,
      description: providerInfo.description,
      is_active: providerInfo.is_active,
      models: models.sort((a, b) => {
        // 默认模型排在前面
        if (a.model_name === defaultLLM.value) return -1
        if (b.model_name === defaultLLM.value) return 1
        // 启用的模型排在前面
        if (a.enabled && !b.enabled) return -1
        if (!a.enabled && b.enabled) return 1
        // 按名称排序
        return a.model_name.localeCompare(b.model_name)
      })
    }

    groups.push(group)
  })

  // 按厂家名称排序
  groups.sort((a, b) => a.display_name.localeCompare(b.display_name))

  llmConfigGroups.value = groups
}

// 获取厂家显示名称
const getProviderDisplayName = (providerId: string) => {
  const provider = providers.value.find(p => p.name === providerId)
  return provider?.display_name || providerId
}

// 获取厂家标签类型
const getProviderTagType = (provider: string): 'primary' | 'success' | 'warning' | 'info' | 'danger' => {
  const typeMap: Record<string, 'primary' | 'success' | 'warning' | 'info' | 'danger'> = {
    'openai': 'primary',
    'google': 'success',
    'anthropic': 'warning',
    'dashscope': 'info',
    'qwen': 'info',
    'zhipu': 'danger',
    'deepseek': 'primary',
    'qianfan': 'success'
  }
  return typeMap[provider.toLowerCase()] || 'info' as const
}

// 格式化价格显示（去除尾部多余的零）
const formatPrice = (price: number | undefined | null) => {
  if (price === undefined || price === null) {
    return '0'
  }
  // 转换为字符串并去除尾部多余的零
  return parseFloat(price.toFixed(6)).toString()
}

const showAddLLMDialog = () => {
  currentLLMConfig.value = null
  isEditingLLM.value = false
  llmDialogVisible.value = true
}

const editLLMConfig = (config: LLMConfig) => {
  currentLLMConfig.value = config
  isEditingLLM.value = true
  llmDialogVisible.value = true
}

const handleLLMConfigSuccess = () => {
  loadLLMConfigs()
}

// 为厂家添加模型
const addModelToProvider = (providerRow: any) => {
  // 预设厂家信息
  currentLLMConfig.value = {
    provider: providerRow.provider,
    model_name: '',
    model_display_name: '',
    description: '',
    enabled: true,
    max_tokens: DEFAULT_MAX_TOKENS,
    temperature: DEFAULT_TEMPERATURE,
    timeout: DEFAULT_TIMEOUT,
    retry_times: DEFAULT_RETRY_TIMES,
    priority: 0,
    api_base: '',
    model_category: '',
    enable_memory: false,
    enable_debug: false
  }

  llmDialogVisible.value = true
  isEditingLLM.value = false
}

// 切换厂家状态
const toggleProviderStatus = async (providerRow: any) => {
  try {
    const newStatus = !providerRow.is_active
    const action = newStatus ? '启用' : '禁用'

    // 获取厂家ID
    const provider = providers.value.find(p => p.name === providerRow.provider)
    if (!provider) {
      ElMessage.error('找不到厂家信息')
      return
    }

    // 调用后端API切换厂家状态
    await configApi.toggleLLMProvider(provider.id, newStatus)

    // 重新加载厂家信息映射和分组数据（厂家列表 + 模型配置 + 分组）
    await load()

    ElMessage.success(`厂家已${action}`)
  } catch (error) {
    console.error('切换厂家状态失败:', error)
    ElMessage.error('切换厂家状态失败')
  }
}

// 测试LLM配置
const testLLMConfig = async (config: LLMConfig) => {
  try {
    const result = await configApi.testConfig({
      config_type: 'llm',
      config_data: config
    })

    if (result.success) {
      ElMessage.success(`测试成功: ${result.message}`)
    } else {
      ElMessage.error(`测试失败: ${result.message}`)
    }
  } catch (error: any) {
    console.error('❌ 测试配置失败:', error)
    console.error('❌ 错误详情:', error.response?.data)
    ElMessage.error(error.response?.data?.detail || error.message || '测试配置失败')
  }
}

// 切换LLM配置启用状态
const toggleLLMConfig = async (config: LLMConfig) => {
  try {
    const newStatus = !config.enabled
    const action = newStatus ? '启用' : '禁用'

    // 更新配置
    const updateData = {
      ...config,
      enabled: newStatus
    }

    await configApi.updateLLMConfig(updateData)
    await loadLLMConfigs()
    ElMessage.success(`模型已${action}`)
  } catch (error) {
    ElMessage.error('切换模型状态失败')
  }
}

// 删除LLM配置
const deleteLLMConfig = async (config: LLMConfig) => {
  try {
    await ElMessageBox.confirm(
      `确定要删除大模型配置 ${config.provider}/${config.model_name} 吗？`,
      '确认删除',
      { type: 'warning' }
    )

    await configApi.deleteLLMConfig(config.provider, config.model_name)
    await loadLLMConfigs()
    ElMessage.success('大模型配置删除成功')
  } catch (error) {
    if (error !== 'cancel') {
      ElMessage.error('删除大模型配置失败')
    }
  }
}

// tab 激活时加载：厂家信息映射 + 模型配置（含分组构建）
const load = async () => {
  await loadProviderInfoMap()
  await loadLLMConfigs()
}

// 供父组件按 tab 懒加载
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

  .empty-state {
    padding: 60px 20px;
    text-align: center;
  }

  .provider-groups {
    display: flex;
    flex-direction: column;
    gap: 24px;
  }

  .provider-group {
    border: 1px solid var(--el-border-color-light);
    border-radius: 8px;
    overflow: hidden;
    background: var(--el-bg-color);
  }

  .provider-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 16px 20px;
    background: var(--el-fill-color-lighter);
    border-bottom: 1px solid var(--el-border-color-light);

    .provider-info {
      display: flex;
      align-items: center;
      gap: 12px;

      .provider-tag {
        font-weight: 600;
      }

      .model-count {
        font-size: 14px;
        color: var(--el-text-color-regular);
      }

      .status-tag {
        margin-left: 8px;
      }
    }

    .provider-actions {
      display: flex;
      gap: 8px;
    }
  }

  .model-name-cell {
    .model-display-name {
      font-weight: 500;
      color: var(--el-text-color-primary);
      display: flex;
      align-items: center;
    }

    .model-code-text {
      font-size: 12px;
      color: var(--el-text-color-placeholder);
      font-family: 'Courier New', monospace;
      margin-top: 4px;
    }
  }

  .config-cell {
    font-size: 13px;
    color: var(--el-text-color-regular);
    line-height: 1.6;
  }

  .pricing-cell {
    font-size: 13px;
    color: var(--el-text-color-regular);
    line-height: 1.6;
  }

  .text-muted {
    color: var(--el-text-color-placeholder);
  }
}
</style>
