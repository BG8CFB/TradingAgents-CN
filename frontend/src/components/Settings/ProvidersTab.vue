<template>
  <div>
    <el-card class="config-content" shadow="never">
      <template #header>
        <div class="card-header">
          <h3>大模型厂家管理</h3>
          <el-button type="primary" @click="showAddProviderDialog">
            <el-icon><Plus /></el-icon>
            添加厂家
          </el-button>
        </div>
      </template>

      <div v-loading="providersLoading">
        <el-table :data="providers" style="width: 100%">
          <el-table-column label="厂家信息" width="200">
            <template #default="{ row }">
              <div class="provider-info">
                <div class="provider-name">{{ row.display_name }}</div>
                <div class="provider-id">{{ row.name }}</div>
              </div>
            </template>
          </el-table-column>
          <el-table-column label="API密钥" width="120">
            <template #default="{ row }">
              <div class="api-key-status">
                <el-tag
                  :type="row.extra_config?.has_api_key ? 'success' : 'danger'"
                  size="small"
                >
                  {{ row.extra_config?.has_api_key ? '已配置' : '未配置' }}
                </el-tag>
              </div>
            </template>
          </el-table-column>
          <el-table-column prop="description" label="描述" />
          <el-table-column label="状态" width="120">
            <template #default="{ row }">
              <div class="status-column">
                <el-tag :type="row.is_active ? 'success' : 'danger'" size="small">
                  {{ row.is_active ? '启用' : '禁用' }}
                </el-tag>
                <el-tag
                  v-if="row.extra_config?.has_api_key"
                  :type="row.extra_config?.source === 'environment' ? 'warning' : 'success'"
                  size="small"
                  class="key-source-tag"
                >
                  {{ row.extra_config?.source === 'environment' ? 'ENV' : 'DB' }}
                </el-tag>
              </div>
            </template>
          </el-table-column>
          <el-table-column label="类型" width="120">
            <template #default="{ row }">
              <el-tag
                :type="getProviderType(row.supported_features) === 'embedding' ? 'warning' : 'primary'"
                size="small"
              >
                {{ getProviderType(row.supported_features) === 'embedding' ? '向量模型' : '大模型' }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="280" fixed="right">
            <template #default="{ row }">
              <el-button
                size="small"
                @click.stop="editProvider(row)"
              >
                编辑
              </el-button>
              <el-button
                size="small"
                :type="row.is_active ? 'warning' : 'success'"
                @click.stop="toggleProvider(row)"
              >
                {{ row.is_active ? '禁用' : '启用' }}
              </el-button>
              <el-button
                size="small"
                type="danger"
                @click.stop="deleteProvider(row)"
              >
                删除
              </el-button>
            </template>
          </el-table-column>
        </el-table>
      </div>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus } from '@element-plus/icons-vue'
import { configApi, type LLMProvider } from '@/api/config'

// 厂家新增/编辑对话框由父组件持有（「API密钥状态」tab 也会打开），此处仅抛出事件
const emit = defineEmits<{
  'add': []
  'edit': [provider: LLMProvider]
}>()

// 响应式数据
const providers = ref<LLMProvider[]>([])
const providersLoading = ref(false)

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

// 显示添加厂家对话框
const showAddProviderDialog = () => {
  emit('add')
}

// 编辑厂家
const editProvider = (provider: LLMProvider) => {
  emit('edit', provider)
}

// 切换厂家状态
const toggleProvider = async (provider: LLMProvider) => {
  try {
    await configApi.toggleLLMProvider(provider.id, !provider.is_active)
    await loadProviders()
    ElMessage.success(`厂家已${provider.is_active ? '禁用' : '启用'}`)
  } catch (error) {
    ElMessage.error('切换厂家状态失败')
  }
}

// 删除厂家
const deleteProvider = async (provider: LLMProvider) => {
  try {
    await ElMessageBox.confirm(
      `确定要删除厂家 ${provider.display_name} 吗？删除后该厂家下的所有模型配置也将被删除。`,
      '确认删除',
      { type: 'warning' }
    )

    await configApi.deleteLLMProvider(provider.id)
    await loadProviders()
    ElMessage.success('厂家删除成功')
  } catch (error) {
    if (error !== 'cancel') {
      ElMessage.error('删除厂家失败')
    }
  }
}

// 根据 supported_features 推导厂家类型
const getProviderType = (features: string[] = []): string => {
  if (features.includes('embedding') && !features.includes('chat')) return 'embedding'
  return 'llm'
}

// 供父组件按 tab 懒加载，以及厂家对话框保存成功后刷新
defineExpose({ reload: loadProviders })
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

  .provider-info {
    .provider-name {
      font-weight: 500;
      color: var(--el-text-color-primary);
    }

    .provider-id {
      font-size: 12px;
      color: var(--el-text-color-placeholder);
      margin-top: 2px;
    }
  }

  .status-column {
    display: flex;
    flex-direction: column;
    gap: 4px;

    .key-source-tag {
      font-size: 10px;
    }
  }
}
</style>
